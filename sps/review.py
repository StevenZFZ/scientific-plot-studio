"""Translate an existing validated plan into selectable, semantic review rows.

Structural/data changes remain a single transaction so unchecking one row cannot
silently drop a dependency or alter a dataset mapping.
"""
from dataclasses import asdict
import copy

from .commands import run_operations, FIGURE_FIELDS, SERIES_FIELDS, STYLE_FIGURE_FIELDS, STYLE_SERIES_FIELDS

FIELD_NAMES = {"xlabel_size":"X标签字号 (pt)","ylabel_size":"Y标签字号 (pt)","tick_size":"刻度字号 (pt)","legend_size":"图例字号 (pt)",
    "title": "标题", "xlabel": "X 轴标签", "ylabel": "Y 轴标签", "width_mm": "宽度 (mm)",
    "height_mm": "高度 (mm)", "font": "字体", "font_size": "字号 (pt)", "axis_width": "轴线宽 (pt)",
    "xscale": "X 轴比例", "yscale": "Y 轴比例", "xlim": "X 轴范围", "ylim": "Y 轴范围",
    "grid": "网格", "legend": "图例", "box": "四边框", "tick_direction": "刻度方向",
    "label": "图例名称", "kind": "图形类型", "color": "颜色", "width": "线宽 (pt)", "marker": "符号",
    "marker_size": "符号大小 (pt)", "line_style": "线型", "alpha": "不透明度", "visible": "显示状态",
    "y_error": "Y 误差列", "text": "文字", "x": "位置 X", "y": "位置 Y", "size": "字号 (pt)",
}


def review_rows(project, operations):
    candidate = run_operations(project, operations)
    if len(operations) == 1 and operations[0]["op"] == "apply_template":
        return [{"label": "套用模板 · " + operations[0]["template"]["name"],
                 "before": f"{len(project.figure.series)} 条曲线 / {len(project.figure.annotations)} 处注释",
                 "after": f"{len(candidate.figure.series)} 条曲线 / {len(candidate.figure.annotations)} 处注释",
                 "impact": "替换当前图形；保留全部原始数据", "operations": copy.deepcopy(operations)}]
    if any(op['op']=='normalize_publication'for op in operations):
        return [{'label':'期刊轴与字体规范化（完整事务）','before':'原始轴与字体','after':operations,'impact':'保留数据和曲线；整组审查所有目标图页','operations':copy.deepcopy(operations)}]
    before, after = project.figure, candidate.figure
    if project.datasets != candidate.datasets or [s.id for s in before.series] != [s.id for s in after.series] or \
            [a.id for a in before.annotations] != [a.id for a in after.annotations]:
        return [{"label": "数据或对象结构变更（完整事务）", "before": "当前工程", "after": operations,
                 "impact": "含数据或结构，请整组审查", "operations": copy.deepcopy(operations)}]
    rows = []

    def add_rows(old, new, keys, prefix, make_op, style_keys):
        for key in sorted(keys):
            a, b = getattr(old, key), getattr(new, key)
            if a == b:
                continue
            rows.append({"label": f"{prefix} · {FIELD_NAMES.get(key, key)}", "before": copy.deepcopy(a),
                         "after": copy.deepcopy(b), "impact": "样式" if key in style_keys else "标签 / 显示 / 映射",
                         "operations": [make_op({key: copy.deepcopy(b)})]})

    add_rows(before, after, FIGURE_FIELDS, "图形", lambda c: {"op": "set_figure", "changes": c}, STYLE_FIGURE_FIELDS)
    for old, new in zip(before.series, after.series):
        # Any mapping changes outside the property whitelist require full review.
        if (old.dataset, old.x, old.y) != (new.dataset, new.x, new.y):
            raise ValueError("数据映射不能通过属性审查隐式改变")
        add_rows(old, new, SERIES_FIELDS, old.label,
                 lambda c, ident=old.id: {"op": "set_series", "ids": [ident], "changes": c}, STYLE_SERIES_FIELDS)
    for old, new in zip(before.annotations, after.annotations):
        add_rows(old, new, {"text", "x", "y", "size", "color"}, old.text,
                 lambda c, ident=old.id: {"op": "set_annotation", "id": ident, "changes": c}, {"x", "y", "size", "color"})
    # Model validates at most 100 operations; a large expansion stays atomic.
    if sum(len(row["operations"]) for row in rows) > 100:
        return [{"label": "批量变更（完整事务）", "before": "当前工程", "after": operations,
                 "impact": "超过 100 项，整组审查", "operations": copy.deepcopy(operations)}]
    return rows


def selected_operations(rows, selected):
    if len(rows) != len(selected) or any(type(v) is not bool for v in selected):
        raise ValueError("勾选状态与审查行不匹配")
    return [copy.deepcopy(op) for row, take in zip(rows, selected) if take for op in row["operations"]]


def display_value(value):
    import json
    if value is None:
        return "自动"
    if type(value) is bool:
        return "是" if value else "否"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
