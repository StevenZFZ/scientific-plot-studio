"""Versioned JSON object model shared by UI, renderer and Agent API."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

SCHEMA = "sps.project/1"
MULTI_SCHEMA = "sps.project/2"
COLORS = ["#287d95", "#df8652", "#8070ae", "#57a48b"]


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def number(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} 必须为有限数值")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name} 超出范围 {low} … {high}")


def text(value, name):
    if not isinstance(value, str) or len(value) > 10000:
        raise ValueError(f"{name} 必须为字符串（最多 10000 字符）")


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("颜色必须为 #RRGGBB")


def boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f"{name} 必须为布尔值")


@dataclass
class Dataset:
    id: str
    name: str
    columns: dict[str, list[float]]
    source: str = ""
    source_sha256: str = ""
    synthetic: bool = False
    allow_missing: bool = False
    text_columns: list[str] = field(default_factory=list)


@dataclass
class Series:
    id: str
    dataset: str
    x: str
    y: str
    label: str = "Series"
    kind: str = "line"
    color: str = COLORS[0]
    width: float = 1.6
    marker: str = "none"
    marker_size: float = 4.0
    line_style: str = "-"
    alpha: float = 1.0
    visible: bool = True
    y_error: str = ""
    row_range: list[int] | None = None


@dataclass
class Annotation:
    id: str
    text: str
    x: float = .05
    y: float = .95
    size: float = 11
    color: str = "#263841"


@dataclass
class FigureSpec:
    title: str = ""
    xlabel: str = "X"
    ylabel: str = "Y"
    width_mm: float = 160
    height_mm: float = 110
    font: str = "Arial"
    font_size: float = 10
    axis_width: float = 1
    xscale: str = "linear"
    yscale: str = "linear"
    xlim: list[float] | None = None
    ylim: list[float] | None = None
    grid: bool = False
    legend: bool = True
    box: bool = True
    tick_direction: str = "in"
    legend_location: str = "best"
    legend_frame: bool = False
    x_major_step: float | None = None
    y_major_step: float | None = None
    minor_divisions: int = 0
    xlabel_size: float | None = None
    ylabel_size: float | None = None
    tick_size: float | None = None
    legend_size: float | None = None
    xtick_values: list[float] | None = None
    xtick_labels: list[str] | None = None
    xtick_dataset: str | None = None
    xtick_column: str | None = None
    axis_sides: dict | None = None
    layout_mode: str = "source"
    label_wrap: bool = False
    series: list[Series] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class GraphLayer:
    id: str
    name: str
    figure: FigureSpec
    rect: list[float] | None = None
    axes_visible: bool = True
    issues: list[str] = field(default_factory=list)


@dataclass
class GraphPage:
    id: str
    name: str
    layers: list[GraphLayer]
    source_index: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class Project:
    name: str = "Untitled"
    schema: str = SCHEMA
    datasets: list[Dataset] = field(default_factory=list)
    figure: FigureSpec = field(default_factory=FigureSpec)
    audit: list[dict] = field(default_factory=list)
    pages: list[GraphPage] = field(default_factory=list)
    origin: dict = field(default_factory=dict)

    def __post_init__(self):
        self._context = (0, 0)
        if self.pages:
            if self.schema==SCHEMA:self.schema = MULTI_SCHEMA
            if self.pages[0].layers:
                self.figure = self.pages[0].layers[0].figure

    @property
    def context(self):
        return self._context

    def _sync_context(self):
        if self.pages:
            pi, li = self._context
            self.pages[pi].layers[li].figure = self.figure

    def sync_page_size(self):
        self._sync_context()
        if self.pages:
            for layer in self.pages[self.context[0]].layers:
                layer.figure.width_mm=self.figure.width_mm
                layer.figure.height_mm=self.figure.height_mm

    def select_context(self, page_index, layer_index=0):
        if type(page_index) is not int or type(layer_index) is not int:
            raise ValueError('图页/图层索引必须为整数')
        if not self.pages:
            if (page_index, layer_index) != (0, 0): raise ValueError('图页不存在')
            return
        if not 0 <= page_index < len(self.pages) or not 0 <= layer_index < len(self.pages[page_index].layers):
            raise ValueError('图页或图层不存在')
        self._sync_context()
        self._context = (page_index, layer_index)
        self.figure = self.pages[page_index].layers[layer_index].figure

    def to_dict(self):
        self._sync_context()
        data = asdict(self)
        for dataset in data['datasets']:
            if not dataset['allow_missing']: dataset.pop('allow_missing')
            if not dataset['text_columns']:dataset.pop('text_columns')
        if self.pages:
            data.pop('figure')
        else:
            data.pop('pages'); data.pop('origin')
            for key in ('xlabel_size','ylabel_size','tick_size','legend_size','xtick_values','xtick_labels','xtick_dataset','xtick_column'):
                if data['figure'][key] is None:data['figure'].pop(key)
            if data['figure']['axis_sides'] is None:data['figure'].pop('axis_sides')
            if data['figure']['layout_mode']=='source':data['figure'].pop('layout_mode')
            if not data['figure']['label_wrap']:data['figure'].pop('label_wrap')
            for series in data['figure']['series']:
                if series['row_range']is None:series.pop('row_range')
        return data

    def fingerprint(self):
        return hashlib.sha256(canonical(self.to_dict()).encode()).hexdigest()

    def clone(self):
        result = from_dict(self.to_dict())
        result.select_context(*self.context)
        return result

    def validate(self):
        if self.pages:
            return self._validate_pages()
        if self.schema != SCHEMA:
            raise ValueError(f"不支持的工程版本: {self.schema}")
        text(self.name, "工程名")
        ids = set()
        datasets = {}
        for d in self.datasets:
            text(d.id, "数据 ID")
            if not d.id or d.id in ids:
                raise ValueError("对象 ID 重复或为空")
            ids.add(d.id)
            datasets[d.id] = d
            text(d.name, "数据名")
            text(d.source, "来源")
            text(d.source_sha256, "来源摘要")
            boolean(d.synthetic, "合成标志")
            boolean(d.allow_missing, "缺失值显式保留")
            if not isinstance(d.columns, dict) or len(d.columns) < 2:
                raise ValueError("数据至少需要两列")
            if not isinstance(d.text_columns,list)or len(set(d.text_columns))!=len(d.text_columns)or any(k not in d.columns for k in d.text_columns):raise ValueError('文本列声明无效')
            lengths = set()
            for name, values in d.columns.items():
                text(name, "列名")
                if not name or not isinstance(values, list) or not values:
                    raise ValueError("空列或列格式错误")
                lengths.add(len(values))
                for value in values:
                    if value is None and d.allow_missing: continue
                    if name in d.text_columns and isinstance(value,str):text(value,'文本单元格');continue
                    number(value, name)
            if len(lengths) != 1:
                raise ValueError("数据列长度不一致")
        if self.origin:raise ValueError('来源记录需要多页工程格式')
        f = self.figure
        for name in ("title", "xlabel", "ylabel", "font"):
            text(getattr(f, name), name)
        number(f.width_mm, "宽 mm", 40, 600)
        number(f.height_mm, "高 mm", 40, 600)
        number(f.font_size, "字号", 5, 48)
        for key in ('xlabel_size','ylabel_size','tick_size','legend_size'):
            if getattr(f,key) is not None:number(getattr(f,key),key,5,96)
        if (f.xtick_values is None)!=(f.xtick_labels is None):raise ValueError('行标签刻度需同时指定值和文本')
        if f.xtick_values is not None:
            if not isinstance(f.xtick_values,list)or not isinstance(f.xtick_labels,list)or len(f.xtick_values)!=len(f.xtick_labels)or len(f.xtick_values)>5000:raise ValueError('行标签刻度格式无效')
            for v in f.xtick_values:number(v,'行标签位置')
            for v in f.xtick_labels:text(v,'行标签')
            if f.xscale!='linear':raise ValueError('行标签刻度仅支持线性轴')
        if (f.xtick_dataset is None)!=(f.xtick_column is None):raise ValueError('行标签数据源不完整')
        if f.xtick_dataset is not None:
            if f.xtick_dataset not in datasets or f.xtick_column not in datasets[f.xtick_dataset].columns:raise ValueError('行标签引用不存在')
        if f.axis_sides is not None:
            if not isinstance(f.axis_sides,dict)or set(f.axis_sides)!={'bottom','top','left','right'}:raise ValueError('坐标轴需明确四边设置')
            for side,settings in f.axis_sides.items():
                if not isinstance(settings,dict)or set(settings)!={'spine','ticks','labels'}:raise ValueError('轴边设置需为框线/刻度/数字')
                for value in settings.values():boolean(value,'轴边显隐')
        if f.layout_mode not in ('source','auto'):raise ValueError('不支持的排版模式')
        boolean(f.label_wrap,'轴标签自动换行')
        number(f.axis_width, "轴宽", .1, 5)
        if f.legend_location not in ("best", "upper right", "upper left", "lower left", "lower right", "upper center", "lower center", "center left", "center right", "center"):
            raise ValueError("图例位置不支持")
        boolean(f.legend_frame, "图例边框")
        if type(f.minor_divisions) is not int or not 0 <= f.minor_divisions <= 10:
            raise ValueError("次刻度数量需为 0–10 的整数")
        for axis in ("x", "y"):
            step = getattr(f, axis + "_major_step")
            if step is not None:
                number(step, "主刻度间距")
                if step <= 0: raise ValueError("主刻度间距必须大于 0")
            if getattr(f, axis + "scale") == "log" and (step is not None or f.minor_divisions):
                raise ValueError("对数轴请使用自动主刻度并关闭自定义次刻度")
        for name in ("grid", "legend", "box"):
            boolean(getattr(f, name), name)
        if f.tick_direction not in ("in", "out", "inout"):
            raise ValueError("不支持的刻度方向")
        for axis in ("x", "y"):
            scale, limits = getattr(f, axis + "scale"), getattr(f, axis + "lim")
            if scale not in ("linear", "log"):
                raise ValueError("仅支持 linear/log")
            if limits is not None:
                if not isinstance(limits, list) or len(limits) != 2:
                    raise ValueError("轴范围必须为 [min, max] 或 null")
                for v in limits:
                    number(v, "轴范围")
                if limits[0] >= limits[1] or scale == "log" and limits[0] <= 0:
                    raise ValueError("轴范围递增；对数轴下限必须大于 0")
        for s in f.series:
            if not isinstance(s.id, str) or not s.id or s.id in ids:
                raise ValueError("对象 ID 重复或为空")
            ids.add(s.id)
            if s.dataset not in datasets:
                raise ValueError("曲线引用了不存在的数据")
            cols = datasets[s.dataset].columns
            if s.x not in cols or s.y not in cols or s.y_error and s.y_error not in cols:
                raise ValueError("曲线引用了不存在的列")
            if s.y in datasets[s.dataset].text_columns or s.y_error in datasets[s.dataset].text_columns:raise ValueError('Y/误差列需为数值')
            if s.x in datasets[s.dataset].text_columns and f.xtick_values is None:raise ValueError('文本X需明确的原始行标签刻度')
            if s.row_range is not None:
                if not isinstance(s.row_range,list)or len(s.row_range)!=2 or any(type(v)is not int for v in s.row_range)or not 0<=s.row_range[0]<s.row_range[1]<=len(cols[s.x]):raise ValueError('曲线行范围无效')
            if s.kind not in ("line", "scatter", "bar", "errorbar"):
                raise ValueError("不支持的图形类型")
            if s.marker not in ("none", "o", "s", "^", "D", "+", "x", "."):
                raise ValueError("不支持的符号")
            if s.line_style not in ("-", "--", ":", "-."):
                raise ValueError("不支持的线型")
            color(s.color)
            text(s.label, "图例")
            boolean(s.visible, "显示状态")
            number(s.width, "线宽", .1, 10)
            number(s.marker_size, "符号大小", 1, 25)
            number(s.alpha, "不透明度", .01, 1)
            if s.kind == "errorbar" and not s.y_error:
                raise ValueError("误差棒需要误差列")
            if s.y_error and any(v < 0 for v in cols[s.y_error] if v is not None):
                raise ValueError("误差值不能为负")
            if s.visible:
                for axis in ("x", "y"):
                    if getattr(f, axis + "scale") == "log" and not datasets[s.dataset].allow_missing and any(v <= 0 for v in cols[getattr(s, axis)] if v is not None and type(v)in(int,float)):
                        raise ValueError("对数轴数据必须全部大于 0；请明确处理无效点")
        for a in f.annotations:
            if not isinstance(a.id, str) or not a.id or a.id in ids:
                raise ValueError("对象 ID 重复或为空")
            ids.add(a.id)
            text(a.text, "注释")
            number(a.x, "注释 x", 0, 1)
            number(a.y, "注释 y", 0, 1)
            number(a.size, "注释字号", 5, 48)
            color(a.color)
        if not isinstance(self.audit, list) or any(not isinstance(x, dict) for x in self.audit):
            raise ValueError("审计记录必须为对象数组")
        canonical(self.to_dict())
        return self


    def _validate_pages(self):
        if self.schema != MULTI_SCHEMA or not 1 <= len(self.pages) <= 512:
            raise ValueError('多页工程版本或图页数量无效')
        if any(not page.layers for page in self.pages):raise ValueError('图页没有图层')
        self._sync_context()
        text(self.name, '工程名')
        identifiers = {d.id for d in self.datasets}
        for page in self.pages:
            for value in (page.id, page.name): text(value, '图页名称/ID')
            if not page.id or page.id in identifiers: raise ValueError('图页ID重复或为空')
            identifiers.add(page.id)
            if type(page.source_index) is not int or page.source_index < 0: raise ValueError('源图序号无效')
            if not 1 <= len(page.layers) <= 128: raise ValueError('图页需有1–128层')
            for issue in page.issues: text(issue, '转换范围')
            if any((l.figure.width_mm,l.figure.height_mm)!=(page.layers[0].figure.width_mm,page.layers[0].figure.height_mm)for l in page.layers):raise ValueError('同一图页的物理尺寸必须一致')
            for layer in page.layers:
                text(layer.id, '图层ID');text(layer.name, '图层名称')
                boolean(layer.axes_visible,'图层轴显隐')
                if not layer.id or layer.id in identifiers: raise ValueError('图层ID重复或为空')
                identifiers.add(layer.id)
                if layer.rect is not None:
                    if not isinstance(layer.rect,list) or len(layer.rect)!=4: raise ValueError('图层范围需为[left,bottom,width,height]')
                    for v in layer.rect:number(v,'图层范围',0,1)
                    x,y,w,h=layer.rect
                    if w<=0 or h<=0 or x+w>1.000001 or y+h>1.000001:raise ValueError('图层超出页面')
                for issue in layer.issues:text(issue,'转换范围')
                Project(self.name,datasets=self.datasets,figure=layer.figure,audit=self.audit).validate()
                for obj in layer.figure.series+layer.figure.annotations:
                    if obj.id in identifiers:raise ValueError('对象ID跨图页重复')
                    identifiers.add(obj.id)
        if not isinstance(self.origin,dict):raise ValueError('原始读取记录必须为对象')
        canonical(asdict(self))
        return self


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def construct(cls, data):
    if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
        raise ValueError(f"{cls.__name__} 包含未知字段或格式错误")
    try:
        return cls(**data)
    except TypeError as e:
        raise ValueError(f"{cls.__name__} 缺少字段") from e


def migrate_figure_options(figure):
    """Upgrade pre-0.8 sps.project/1 figure options without changing data.

    Old clipboard/PPT hashes are verified on their original payload first.
    Missing settings get the previous renderer's visible defaults.
    """
    upgraded = dict(figure)
    for key, value in {"legend_location": "best", "legend_frame": False,
                       "x_major_step": None, "y_major_step": None, "minor_divisions": 0}.items():
        upgraded.setdefault(key, value)
    return upgraded


def _figure_from_dict(data):
    f = migrate_figure_options(data)
    f['series'] = [construct(Series, s) for s in f.get('series', [])]
    f['annotations'] = [construct(Annotation, a) for a in f.get('annotations', [])]
    return construct(FigureSpec, f)


def from_dict(data):
    if not isinstance(data, dict): raise ValueError('工程必须为JSON对象')
    if data.get('schema') not in (SCHEMA,MULTI_SCHEMA):raise ValueError('缺少或不支持的SPS工程版本')
    data=dict(data)
    data['datasets']=[construct(Dataset,d) for d in data.get('datasets',[])]
    if data['schema']==MULTI_SCHEMA:
        if 'figure' in data:raise ValueError('多页工程不能同时包含旧版figure')
        pages=[]
        for source_page in data.get('pages',[]):
            p=dict(source_page);layers=[]
            for source_layer in p.get('layers',[]):
                layer=dict(source_layer);layer['figure']=_figure_from_dict(layer.get('figure',{}))
                layers.append(construct(GraphLayer,layer))
            p['layers']=layers;pages.append(construct(GraphPage,p))
        if not pages:raise ValueError('多页工程没有图页')
        data['pages']=pages
    else:
        if 'pages' in data or 'origin' in data:raise ValueError('旧版工程不接受多页字段')
        data['figure']=_figure_from_dict(data.get('figure',{}))
    return construct(Project,data).validate()


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 50_000_000:
        raise ValueError("MVP 单文件上限为 50 MB")
    return json.loads(path.read_text(encoding="utf-8"))


def load(path):
    return from_dict(read_json(path))


def write_json(path, data):
    """Atomic save in destination directory. Never truncate an existing project."""
    import os
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    fd, temp = tempfile.mkstemp(prefix=".sps-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save(project, path):
    project.validate()
    write_json(path, project.to_dict())


def demo():
    import numpy as np
    x = np.linspace(400, 850, 121)
    d = Dataset("data_demo", "Synthetic emission · 演示数据", {
        "Wavelength": x.tolist(),
        "Reference": (np.exp(-((x - 610) / 72) ** 2) * .82 + .025).tolist(),
        "Modified": (np.exp(-((x - 660) / 60) ** 2) * .96 + .025).tolist(),
        "Error": [0.025] * len(x),
    }, synthetic=True)
    return Project(name="Emission study · synthetic demo", datasets=[d], figure=FigureSpec(
        title="Synthetic emission spectra", xlabel="Wavelength (nm)", ylabel="Normalized intensity (a.u.)",
        series=[Series("series_ref", d.id, "Wavelength", "Reference", "Reference", color=COLORS[0]),
                Series("series_mod", d.id, "Wavelength", "Modified", "Modified", color=COLORS[1])],
    )).validate()
