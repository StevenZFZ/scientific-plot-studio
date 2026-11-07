"""Journal and Origin-inspired built-in templates.

Every entry states the publisher's published figure guidance next to the SPS
choice, because a template is a starting point, not a compliance certificate.
Sizes, fonts and tick rules below come from the publishers' own author pages;
palettes follow widely used colour-blind-safe and journal-adjacent conventions.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import FigureSpec, Series
from .commands import FIGURE_FIELDS, STYLE_SERIES_FIELDS
from .templates import NativeTemplate, PlotSlot

# Okabe & Ito (2008) colour-universal palette, minus the pale yellow that
# disappears on white at print sizes.
OKABE_ITO = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9", "#E69F00"]
# ggsci "NPG" palette, common in Nature-adjacent figures.
NPG = ["#E64B35", "#4DBBD5", "#00A087", "#3C5488", "#F39B7F", "#8491B4"]
# AAAS/Science-adjacent saturated palette.
AAAS = ["#3B4992", "#EE0000", "#008B45", "#631879", "#008280", "#BB0021"]
GRAY = ["#000000", "#5A5A5A", "#8C8C8C", "#B5B5B5"]
SLIDES = ["#0A84FF", "#FF9F0A", "#30D158", "#FF375F"]


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    width: float
    height: float
    font_size: float
    colors: tuple
    axis_width: float = 0.6
    tick_direction: str = "in"
    box: bool = False
    grid: bool = False
    legend_location: str = "best"
    legend_frame: bool = False
    markers: tuple = ("none", "none", "none", "none")
    line_styles: tuple = ("-", "-", "-", "-")
    line_width: float = 1.0
    marker_size: float = 3.5
    kind: str = "line"
    slots: int = 3
    description: str = ""


PRESETS = [
    Preset("nature_single", "Nature · 单栏（89 mm）", 89, 60, 7, NPG,
           axis_width=0.5, line_width=0.9, legend_location="best",
           description="Nature 研究图建议单栏 89 mm、图内文字 5–7 pt。"
                       "SPS 取 7 pt、隐藏上/右框线、内向刻度、无网格、图例无边框；轴样式是 SPS 的选择，非期刊强制。"),
    Preset("nature_double", "Nature · 双栏（183 mm）", 183, 110, 7, NPG,
           axis_width=0.5, line_width=0.9, legend_location="best",
           description="Nature 研究图双栏宽 183 mm、文字 5–7 pt。SPS 取 7 pt 与单栏相同的轴规则；"
                       "适合多组曲线并排，仍需逐图检查标签与图例遮挡。"),
    Preset("nature_errorbar", "Nature · 误差棒（89 mm）", 89, 65, 7, NPG,
           axis_width=0.5, line_width=0.9, kind="errorbar", slots=1, marker_size=3.2,
           description="Nature 单栏尺寸下的误差棒模板。绑定数据时必须明确选择 Y 误差列，"
                       "SPS 不推断误差含义；柱状/散点误差棒请在曲线页切换类型。"),
    Preset("science_single", "Science · 单栏（55 mm）", 55, 50, 6.5, AAAS,
           axis_width=0.5, line_width=0.8, legend_location="best", slots=2,
           description="Science 单栏约 55 mm、双栏 120 mm，图内文字通常 5–7 pt。"
                       "SPS 取 6.5 pt、隐藏上/右框线、内向刻度；窄栏下建议只放 1–2 条曲线。"),
    Preset("cell_double", "Cell Press · 双栏（174 mm）", 174, 120, 7, NPG,
           axis_width=0.6, tick_direction="out", line_width=1.0,
           description="Cell Press 双栏宽 174 mm（单栏 85 mm）。SPS 取 7 pt、外向刻度、无上/右框线；"
                       "外向刻度是本模板的版式选择，需与同刊已发表图对照。"),
    Preset("acs_single", "ACS · 单栏（82.5 mm）", 82.5, 60, 8, AAAS,
           axis_width=0.75, box=True, line_width=1.0,
           description="ACS 期刊单栏上限约 240 pt（≈84.7 mm）、文字不小于 4.5 pt。"
                       "SPS 取 82.5 mm、8 pt、四边框、内向刻度；8 pt 是 SPS 选择而非 ACS 硬性要求。"),
    Preset("ieee_double", "IEEE · 双栏（181 mm）", 181, 105, 8, AAAS,
           axis_width=0.7, line_width=1.0, legend_location="best",
           description="IEEE 双栏正文宽 181 mm（单栏 88.9 mm），图内文字常用 8 pt。"
                       "SPS 取 8 pt、隐藏上/右框线、内向刻度、无网格；IEEE 正文用 Times，图内仍按你的 Arial 默认。"),
    Preset("elsevier_double", "Elsevier · 双栏（190 mm）", 190, 120, 8, NPG,
           axis_width=0.7, box=True, line_width=1.0,
           description="Elsevier 通用建议：单栏 90 mm、1.5 栏 140 mm、双栏 190 mm，普通文字 7 pt、上下标不小于 6 pt。"
                       "SPS 取 190 mm、8 pt、四边框；具体期刊指南优先于本模板。"),
    Preset("colorblind", "色盲安全 · Okabe–Ito", 160, 110, 9, OKABE_ITO,
           axis_width=0.8, line_width=1.4, markers=("o", "s", "^", "D"), marker_size=4.0,
           legend_location="best",
           description="使用 Okabe–Ito 色盲通用配色，并叠加点形区分，黑白打印与红绿色觉障碍下仍可分辨。"
                       "6 色以内最稳；超过 6 条曲线请改用分面或多图。"),
    Preset("grayscale", "灰度印刷 · 线型区分", 160, 110, 9, GRAY,
           axis_width=0.8, box=True, line_width=1.3,
           markers=("o", "s", "^", "D"), marker_size=4.0,
           line_styles=("-", "--", ":", "-."), legend_location="best",
           description="黑白印刷或单色期刊用：灰阶 + 点形 + 线型三重区分，不依赖颜色。"
                       "灰色过浅时请提高对比或改为全黑加线型。"),
    Preset("slides", "汇报幻灯片（200 mm）", 200, 120, 14, SLIDES,
           axis_width=1.2, box=True, grid=True, line_width=2.2, marker_size=5.0,
           legend_location="best", legend_frame=True,
           description="组会与答辩用：14 pt 字号、加粗线条、浅网格、图例带边框。"
                       "这是演示版式，不符合期刊投稿尺寸，投稿前请换用期刊模板。"),
]


def _figure(preset):
    spec = FigureSpec(
        title="{{title}}", xlabel="{{x_label}}", ylabel="{{y_label}}",
        width_mm=preset.width, height_mm=preset.height,
        font="Arial", font_size=preset.font_size,
        axis_width=preset.axis_width, tick_direction=preset.tick_direction,
        box=preset.box, grid=preset.grid,
        legend=True, legend_location=preset.legend_location, legend_frame=preset.legend_frame,
        xlabel_size=preset.font_size, ylabel_size=preset.font_size,
        tick_size=preset.font_size, legend_size=round(preset.font_size * 0.9, 2),
        minor_divisions=0, label_wrap=True, layout_mode="auto",
    )
    return {key: getattr(spec, key) for key in sorted(FIGURE_FIELDS)}


def _slots(preset):
    slots = []
    for index in range(preset.slots):
        series = Series(
            "dummy", "data", "x", "y",
            label=f"曲线 {index + 1}",
            kind=preset.kind,
            color=preset.colors[index % len(preset.colors)],
            width=preset.line_width,
            marker=preset.markers[index % len(preset.markers)],
            marker_size=preset.marker_size,
            line_style=preset.line_styles[index % len(preset.line_styles)],
        )
        fields = STYLE_SERIES_FIELDS | {"kind"}
        slots.append(PlotSlot(f"plot_{index + 1}", f"曲线 {index + 1}",
                              {key: getattr(series, key) for key in sorted(fields)}))
    return slots


def builtin_templates():
    result = []
    for preset in PRESETS:
        template = NativeTemplate(
            id="builtin_" + preset.key,
            name=preset.name,
            figure=_figure(preset),
            slots=_slots(preset),
            description=preset.description,
            source={"kind": "manual", "name": "SPS"},
        )
        result.append(template.validate())
    return result
