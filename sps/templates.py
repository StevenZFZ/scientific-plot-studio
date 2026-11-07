"""Data-independent single-axes templates and explicit bindings.

No Origin parser, external code execution, implicit unit conversions or plot-data
inference. A template application becomes one reviewable command transaction.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
import re

from .model import Project, Dataset, FigureSpec, Series, Annotation, canonical, construct, text, read_json, write_json
from .commands import FIGURE_FIELDS, STYLE_SERIES_FIELDS

SCHEMA = "sps.template/1"
PARTIAL_ORIGIN_SCHEMA = "sps.template/2"
SUPPORTED_SCHEMAS = {SCHEMA, PARTIAL_ORIGIN_SCHEMA}
SLOT_FIELDS = STYLE_SERIES_FIELDS | {"kind", "visible"}
GLOBAL_TOKENS = {"title", "x_label", "y_label"}
SLOT_TOKENS = GLOBAL_TOKENS | {"series_name", "x_column", "y_column"}
TOKEN = re.compile(r"\{\{([^{}]+)\}\}")


@dataclass
class PlotSlot:
    id: str
    name: str
    properties: dict
    label: str = "{{series_name}}"


@dataclass
class NativeTemplate:
    id: str
    name: str
    figure: dict
    slots: list[PlotSlot]
    schema: str = SCHEMA
    description: str = ""
    annotations: list[dict] = field(default_factory=list)
    source: dict = field(default_factory=lambda: {"kind": "manual"})

    def to_dict(self):
        return asdict(self)

    def fingerprint(self):
        return hashlib.sha256(canonical(self.to_dict()).encode()).hexdigest()

    def validate(self):
        if self.schema not in SUPPORTED_SCHEMAS:
            raise ValueError("不支持的 SPS 模板版本")
        for name in ("id", "name", "description"):
            text(getattr(self, name), name)
        if not self.id or not self.name.strip():
            raise ValueError("模板 ID 和名称不能为空")
        if not isinstance(self.figure, dict) or set(self.figure) - FIGURE_FIELDS:
            raise ValueError("模板画布含未知字段")
        if not isinstance(self.source, dict) or set(self.source) - {"kind", "name", "project_hash", "source_sha256", "mapping_report_hash"}:
            raise ValueError("模板来源字段不支持")
        if self.source.get("kind") not in ("manual", "native", "origin_partial"):
            raise ValueError("当前只支持 SPS 原生模板；Origin 模板解析尚未实现")
        if (self.source.get("kind") == "origin_partial") != (self.schema == PARTIAL_ORIGIN_SCHEMA):
            raise ValueError("Origin 部分模板使用 sps.template/2；原生模板继续使用 sps.template/1")
        if self.source.get("kind") == "origin_partial":
            if not all(isinstance(self.source.get(k), str) and re.fullmatch(r"[a-f0-9]{64}", self.source[k])
                       for k in ("source_sha256", "mapping_report_hash")):
                raise ValueError("Origin 部分模板必须保留源文件与映射报告摘要")
            if not self.description.strip():
                raise ValueError("Origin 部分模板必须保留转换范围说明")
        for value in self.source.values():
            text(value, "模板来源")
        if not isinstance(self.slots, list) or not 1 <= len(self.slots) <= 32:
            raise ValueError("原生模板需要 1–32 个曲线槽位")
        ids = set()
        for slot in self.slots:
            text(slot.id, "槽位 ID")
            text(slot.name, "槽位名称")
            text(slot.label, "图例规则")
            if not slot.id or slot.id in ids:
                raise ValueError("模板槽位 ID 重复或为空")
            ids.add(slot.id)
            if not isinstance(slot.properties, dict) or set(slot.properties) - SLOT_FIELDS:
                raise ValueError("曲线槽位包含数据引用或未知样式字段")
            validate_tokens(slot.label, SLOT_TOKENS)
        for key in ("title", "xlabel", "ylabel"):
            validate_tokens(self.figure.get(key, ""), GLOBAL_TOKENS)
        if not isinstance(self.annotations, list) or len(self.annotations) > 64:
            raise ValueError("模板最多支持 64 个文本注释")
        for a in self.annotations:
            if not isinstance(a, dict) or set(a) - {"text", "x", "y", "size", "color"} or "text" not in a:
                raise ValueError("模板注释字段不支持")
            validate_tokens(a["text"], GLOBAL_TOKENS)
        # Reuse scientific object validation instead of maintaining another set of
        # numeric, range, type and error-bar rules. This is structural data only.
        dummy = Project(datasets=[Dataset("validation_data", "validation", {"x": [1., 2.], "y": [1., 2.], "e": [.1, .1]}, synthetic=True)])
        bindings = [{"slot": slot.id, "dataset": "validation_data", "x": "x", "y": "y",
                     "y_error": "e" if slot.properties.get("kind") == "errorbar" else ""} for slot in self.slots]
        dummy.figure = _instantiate(dummy, self, bindings, {"title": "Title", "x_label": "X", "y_label": "Y"})
        dummy.validate()
        canonical(self.to_dict())
        return self


def validate_tokens(value, allowed):
    text(value, "模板文字")
    for token in TOKEN.findall(value):
        if token not in allowed:
            raise ValueError(f"未知模板占位符 {{{{{token}}}}}")
    remaining = TOKEN.sub("", value)
    if "{{" in remaining or "}}" in remaining:
        raise ValueError("模板占位符格式不完整")


def substitute(value, context):
    # Single pass string substitution. No eval, expressions or recursive tokens.
    return TOKEN.sub(lambda match: context[match.group(1)], value)


def from_dict(data):
    if not isinstance(data, dict) or data.get("schema") not in SUPPORTED_SCHEMAS:
        raise ValueError("这不是支持的 SPS 原生模板；OTP/OTPU/OTH 尚不能直接导入")
    data = copy.deepcopy(data)
    if not isinstance(data.get("slots"), list):
        raise ValueError("模板缺少曲线槽位")
    data["slots"] = [construct(PlotSlot, slot) for slot in data["slots"]]
    return construct(NativeTemplate, data).validate()


def load(path):
    if Path(path).suffix.lower() in (".otp", ".otpu", ".oth", ".otw", ".otwu", ".otm", ".otmu"):
        raise ValueError("当前无法解析 Origin 模板；请使用 SPS 原生模板，不能仅改扩展名")
    return from_dict(read_json(path))


def save(template, path):
    template.validate()
    if not str(path).endswith(".sps-template.json"):
        raise ValueError("模板必须保存为 .sps-template.json；不能伪装为 Origin 模板")
    write_json(path, template.to_dict())


def extract(project, name=None, keep_ranges=False):
    project.validate()
    if not project.figure.series:
        raise ValueError("当前图形没有曲线，不能提取模板")
    figure = {k: copy.deepcopy(getattr(project.figure, k)) for k in sorted(FIGURE_FIELDS)}
    if project.figure.xtick_dataset is not None:
        raise ValueError('该层使用源数据行标签轴；模板尚需新行标签绑定，不能复制旧数据标签冒充通用模板')
    figure.update(title="{{title}}", xlabel="{{x_label}}", ylabel="{{y_label}}")
    if not keep_ranges:
        figure.update(xlim=None, ylim=None)
    slots = [PlotSlot(f"plot_{i + 1}", s.label,
                      {k: copy.deepcopy(getattr(s, k)) for k in sorted(SLOT_FIELDS)})
             for i, s in enumerate(project.figure.series)]
    # IDs and data references never leak into the reusable template itself.
    annotations = [{k: v for k, v in asdict(a).items() if k != "id"} for a in project.figure.annotations]
    seed = canonical({"figure": figure, "slots": [asdict(s) for s in slots], "annotations": annotations})
    return NativeTemplate(id="template_" + hashlib.sha256(seed.encode()).hexdigest()[:12],
                          name=name or project.name + " template", figure=figure, slots=slots,
                          annotations=annotations, source={"kind": "native", "name": project.name,
                                                           "project_hash": project.fingerprint()}).validate()


def _instantiate(project, template, bindings, labels):
    if not isinstance(labels, dict) or set(labels) != GLOBAL_TOKENS:
        raise ValueError("必须明确提供 title、x_label、y_label；不自动猜测单位")
    for value in labels.values():
        text(value, "轴标签 / 标题")
    if not isinstance(bindings, list) or len(bindings) != len(template.slots):
        raise ValueError("每个模板槽位都需要明确绑定一次新数据")
    by_slot = {}
    datasets = {d.id: d for d in project.datasets}
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) - {"slot", "dataset", "x", "y", "y_error", "legend"} or \
                {"slot", "dataset", "x", "y"} - set(binding):
            raise ValueError("数据绑定字段错误")
        for value in binding.values():
            text(value, "数据绑定")
        if binding["slot"] in by_slot:
            raise ValueError("槽位重复绑定")
        by_slot[binding["slot"]] = binding
    if set(by_slot) != {slot.id for slot in template.slots}:
        raise ValueError("绑定含未知或缺失槽位")
    figure = construct(FigureSpec, copy.deepcopy(template.figure))
    for key in ("title", "xlabel", "ylabel"):
        setattr(figure, key, substitute(getattr(figure, key), labels))
    digest = template.fingerprint()[:12]
    for i, slot in enumerate(template.slots):
        binding = by_slot[slot.id]
        d = datasets.get(binding["dataset"])
        if d is None or binding["x"] not in d.columns or binding["y"] not in d.columns:
            raise ValueError(f"槽位 {slot.name} 引用不存在的数据或列")
        error = binding.get("y_error", "")
        if slot.properties.get("kind", "line") == "errorbar" and not error:
            raise ValueError(f"槽位 {slot.name} 需要明确的 Y 误差列")
        if error and error not in d.columns:
            raise ValueError(f"槽位 {slot.name} 的误差列不存在")
        context = {**labels, "series_name": binding.get("legend", binding["y"]),
                   "x_column": binding["x"], "y_column": binding["y"]}
        figure.series.append(Series(id=f"tpl_curve_{digest}_{i}", dataset=d.id, x=binding["x"], y=binding["y"],
                                    label=substitute(slot.label, context), y_error=error, **copy.deepcopy(slot.properties)))
    for i, raw in enumerate(template.annotations):
        raw = copy.deepcopy(raw)
        raw["text"] = substitute(raw["text"], labels)
        figure.annotations.append(Annotation(id=f"tpl_text_{digest}_{i}", **raw))
    return figure


def instantiate(project, template_data, bindings, labels):
    template = from_dict(template_data)
    figure = _instantiate(project, template, bindings, labels)
    candidate = project.clone()
    candidate.figure = figure
    candidate.validate()
    return figure


def builtin_templates():
    """Journal presets live in their own module to keep this file schema-only."""
    from .journal_templates import builtin_templates as presets
    return presets()


def preview_project(template):
    import numpy as np
    x = np.linspace(.1, 6, 61)
    columns = {"X": x.tolist(), "Error": [.025] * len(x)}
    bindings = []
    for i, slot in enumerate(template.slots):
        name = f"Sample {i + 1}"
        columns[name] = (np.exp(-((x - 2.5 - .6 * i) / 1.2) ** 2) + .05).tolist()
        bindings.append({"slot": slot.id, "dataset": "template_demo", "x": "X", "y": name,
                         "y_error": "Error" if slot.properties.get("kind") == "errorbar" else ""})
    p = Project(name="Template preview · synthetic", datasets=[Dataset("template_demo", "Synthetic preview", columns, synthetic=True)])
    p.figure = instantiate(p, template.to_dict(), bindings, {"title": "Template preview", "x_label": "X", "y_label": "Y"})
    return p.validate()


class TemplateLibrary:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.errors = []

    def items(self):
        self.errors = []
        items = [(t, "内置") for t in builtin_templates()]
        for path in sorted(self.directory.glob("*.sps-template.json")):
            try:
                items.append((load(path), "个人"))
            except Exception as e:
                self.errors.append(f"{path.name}: {e}")
        return items

    def add(self, template):
        template.validate()
        path = self.directory / (template.fingerprint() + ".sps-template.json")
        if not path.exists():
            save(template, path)
        elif load(path).to_dict() != template.to_dict():
            raise ValueError("同名模板文件内容冲突，未覆盖")
        return path
