"""Allowlisted transactions: preview diff, stale-review protection, undo/redo.

No code execution, filesystem access, network calls or arbitrary attribute paths.
"""
from __future__ import annotations

from dataclasses import asdict
import copy
from datetime import datetime, timezone
import hashlib
import uuid

from .model import canonical, from_dict, construct, Dataset, Series, Annotation

FIGURE_FIELDS = {"title", "xlabel", "ylabel", "width_mm", "height_mm", "font", "font_size",
                 "axis_width", "xscale", "yscale", "xlim", "ylim", "grid", "legend", "box", "tick_direction"}
PLOT_OPTION_FIELDS = {"legend_location", "legend_frame", "x_major_step", "y_major_step", "minor_divisions"}
FIGURE_FIELDS |= PLOT_OPTION_FIELDS | {"xlabel_size","ylabel_size","tick_size","legend_size","xtick_values","xtick_labels","xtick_dataset","xtick_column"}
FIGURE_FIELDS |= {"axis_sides","layout_mode","label_wrap"}
SERIES_FIELDS = {"label", "kind", "color", "width", "marker", "marker_size", "line_style", "alpha", "visible", "y_error", "row_range"}
STYLE_FIGURE_FIELDS = {"width_mm", "height_mm", "font", "font_size", "axis_width", "grid", "legend", "box", "tick_direction"}
STYLE_FIGURE_FIELDS |= PLOT_OPTION_FIELDS | {"xlabel_size","ylabel_size","tick_size","legend_size"}
STYLE_FIGURE_FIELDS |= {"axis_sides","layout_mode","label_wrap"}
STYLE_SERIES_FIELDS = {"color", "width", "marker", "marker_size", "line_style", "alpha"}


def style_from_project(project):
    f = project.figure
    return {"schema": "sps.style/1", "name": project.name + " style", "source_project": project.fingerprint(),
            "figure": {k: getattr(f, k) for k in sorted(STYLE_FIGURE_FIELDS)},
            "series": [{k: getattr(s, k) for k in sorted(STYLE_SERIES_FIELDS)} for s in f.series]}


def diff(before, after, path=""):
    result = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(before.keys() | after.keys()):
            result.extend(diff(before.get(k), after.get(k), f"{path}/{k}"))
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for i, (a, b) in enumerate(zip(before, after)):
            result.extend(diff(a, b, f"{path}/{i}"))
    elif before != after:
        result.append({"path": path, "before": before, "after": after})
    return result


def _keys(op, required, optional=()):
    if not isinstance(op, dict) or set(op) - set(required) - set(optional) or set(required) - set(op):
        raise ValueError(f"操作字段不符合约定；必须包含 {sorted(required)}")


def _set(obj, changes, allowed):
    if not isinstance(changes, dict) or not changes or set(changes) - allowed:
        raise ValueError("字段不在操作白名单中")
    for k, v in changes.items():
        setattr(obj, k, copy.deepcopy(v))


def run_operations(project, operations):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise ValueError("每个事务需要 1–100 个操作")
    candidate = project.clone()
    for op in operations:
        name = op.get("op") if isinstance(op, dict) else None
        if name == "set_figure":
            _keys(op, ("op", "changes"))
            _set(candidate.figure, op["changes"], FIGURE_FIELDS)
        elif name == "normalize_publication":
            _keys(op, ('op','profile','size','scope','font'))
            from .publication import apply_profile
            apply_profile(candidate, op['profile'], op['size'], op['scope'], op['font'])
        elif name == "set_series":
            _keys(op, ("op", "ids", "changes"))
            ids = op["ids"]
            known = {s.id for s in candidate.figure.series}
            if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or set(ids) - known:
                raise ValueError("曲线 ID 无效或重复")
            for s in candidate.figure.series:
                if s.id in ids:
                    _set(s, op["changes"], SERIES_FIELDS)
        elif name == "add_dataset":
            _keys(op, ("op", "dataset"))
            candidate.datasets.append(construct(Dataset, op["dataset"]))
        elif name == "add_series":
            _keys(op, ("op", "series"))
            candidate.figure.series.append(construct(Series, op["series"]))
        elif name == "set_cell":
            _keys(op, ("op", "dataset", "column", "row", "value"))
            d = next((d for d in candidate.datasets if d.id == op["dataset"]), None)
            if d is None or op["column"] not in d.columns:
                raise ValueError("数据或列不存在")
            row = op["row"]
            if type(row) is not int or not 0 <= row < len(d.columns[op["column"]]):
                raise ValueError("行号无效")
            d.columns[op["column"]][row] = op["value"]
        elif name == "remove_series":
            _keys(op, ("op", "id"))
            if not any(s.id == op["id"] for s in candidate.figure.series):
                raise ValueError("曲线不存在")
            candidate.figure.series = [s for s in candidate.figure.series if s.id != op["id"]]
        elif name == "add_annotation":
            _keys(op, ("op", "annotation"))
            candidate.figure.annotations.append(construct(Annotation, op["annotation"]))
        elif name == "set_annotation":
            _keys(op, ("op", "id", "changes"))
            a = next((a for a in candidate.figure.annotations if a.id == op["id"]), None)
            if a is None:
                raise ValueError("注释不存在")
            _set(a, op["changes"], {"text", "x", "y", "size", "color"})
        elif name == "remove_annotation":
            _keys(op, ("op", "id"))
            if not any(a.id == op["id"] for a in candidate.figure.annotations):
                raise ValueError("注释不存在")
            candidate.figure.annotations = [a for a in candidate.figure.annotations if a.id != op["id"]]
        elif name == "apply_style":
            _keys(op, ("op", "style"))
            style = op["style"]
            if not isinstance(style, dict) or style.get("schema") != "sps.style/1":
                raise ValueError("不支持的风格格式")
            if set(style) - {"schema", "name", "source_project", "figure", "series"}:
                raise ValueError("风格含未知字段")
            figure_changes = style.get("figure", {})
            if not isinstance(figure_changes, dict):
                raise ValueError("风格画布必须为对象")
            if figure_changes:
                _set(candidate.figure, figure_changes, STYLE_FIGURE_FIELDS)
            palette = style.get("series", [])
            if not isinstance(palette, list):
                raise ValueError("风格曲线必须为数组")
            if any(not isinstance(item, dict) or set(item) - STYLE_SERIES_FIELDS for item in palette):
                raise ValueError("风格曲线字段不支持")
            if not figure_changes and not any(palette):
                raise ValueError("风格没有可应用的属性")
            # Empty curve entries are explicit unmapped placeholders. Preserve
            # palette order; never shift a later source curve onto another slot.
            for i, s in enumerate(candidate.figure.series):
                if palette and palette[i % len(palette)]:
                    _set(s, palette[i % len(palette)], STYLE_SERIES_FIELDS)
        elif name == "apply_template":
            _keys(op, ("op", "template", "bindings", "labels"))
            from .templates import instantiate
            candidate.figure = instantiate(candidate, op["template"], op["bindings"], op["labels"])
        else:
            raise ValueError(f"不支持的操作 {name!r}")
        if candidate.pages and name in ('set_figure','apply_template'):
            candidate.sync_page_size()
    return candidate.validate()


class Session:
    def __init__(self, project):
        self.project = project.validate()
        self._undo = []
        self._redo = []
        self._reviews = {}

    def preview(self, operations):
        candidate = run_operations(self.project, operations)
        changes = diff(self.project.to_dict(), candidate.to_dict())
        plan = {"schema": "sps.review/1", "base_hash": self.project.fingerprint(),
                "operations": copy.deepcopy(operations), "changes": changes,
                "result_hash": candidate.fingerprint()}
        if self.project.pages:
            pi,li=self.project.context
            plan['target']={'page':self.project.pages[pi].id,'layer':self.project.pages[pi].layers[li].id}
        plan["digest"] = hashlib.sha256(canonical(plan).encode()).hexdigest()
        return plan

    def apply_review(self, plan, actor="agent"):
        if not isinstance(plan, dict) or plan.get("schema") != "sps.review/1":
            raise ValueError("无效审查计划")
        if plan.get("base_hash") != self.project.fingerprint():
            raise ValueError("工程已变化，审查已过期；请重新预览")
        verified = self.preview(plan.get("operations"))
        if canonical(verified) != canonical(plan):
            raise ValueError("审查内容被更改，请重新预览")
        return self.execute(plan["operations"], actor=actor)

    def execute(self, operations, actor="user"):
        candidate = run_operations(self.project, operations)
        if candidate.fingerprint() == self.project.fingerprint():
            return self.project
        self._undo.append(self._snapshot())
        self._redo.clear()
        candidate.audit.append({"time": datetime.now(timezone.utc).isoformat(), "actor": str(actor),
                                "action": "transaction", "operations": copy.deepcopy(operations)})
        self.project = candidate
        return candidate

    def _snapshot(self):
        data=self.project.to_dict()
        return {'document':data,'context':list(self.project.context)} if self.project.pages else data

    def _restore(self, source, destination, action):
        if not source:
            return False
        destination.append(self._snapshot())
        frame=source.pop()
        restored = from_dict(frame['document'] if 'document' in frame else frame)
        if 'document' in frame:restored.select_context(*frame['context'])
        # Audit remains append-only even while content is restored.
        restored.audit = copy.deepcopy(self.project.audit) + [{"time": datetime.now(timezone.utc).isoformat(),
                                                            "actor": "user", "action": action}]
        self.project = restored
        return True

    def undo(self):
        return self._restore(self._undo, self._redo, "undo")

    def redo(self):
        return self._restore(self._redo, self._undo, "redo")
