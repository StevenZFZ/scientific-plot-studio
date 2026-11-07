"""Product interoperability adapter: native Office XY chart and embedded SPS data.

python-pptx is used as the runtime serializer for the Python desktop product,
not as a slide-design authoring workflow. Office and SPS use different renderers.
"""
import io
import json
from pathlib import Path
from contextlib import contextmanager

from .model import canonical
from .transfer import encode, decode
from .office import package, read_part, sha

PART = 'sps/project.json'
REL_TYPE = 'https://scientific-plot-studio.org/relationships/project'


def export(project, path):
    from pptx import Presentation
    from pptx.chart.data import XyChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_TICK_MARK, XL_LEGEND_POSITION
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    from pptx.util import Mm, Pt
    from pptx.opc.package import Part
    from pptx.opc.packuri import PackURI
    from pptx.chart.xlsx import XyWorkbookWriter
    from xlsxwriter import Workbook

    class LiteralWriter(XyWorkbookWriter):
        @contextmanager
        def _open_worksheet(self, stream):
            with Workbook(stream, {'in_memory': True, 'strings_to_formulas': False,
                                   'strings_to_urls': False}) as workbook:
                yield workbook, workbook.add_worksheet()

    class LiteralData(XyChartData):
        @property
        def _workbook_writer(self): return LiteralWriter(self)

    project.validate(); path = Path(path)
    if project.pages:raise ValueError('多页/多层工程的原生PPTX映射尚未实现；请逐图导出图像，不会只导出一层')
    if path.exists(): raise ValueError('PPTX 已存在，请选择新名字')
    f = project.figure; visible = [s for s in f.series if s.visible]
    if not visible or any(s.kind != 'line' or s.marker != 'none' or s.alpha != 1 for s in visible):
        raise ValueError('可编辑 PPTX 首版仅支持不透明、无符号的纯折线；其他图型请用图像导出')
    if f.annotations or f.xscale != 'linear' or f.yscale != 'linear':
        raise ValueError('可编辑 PPTX 首版不支持注释与对数轴；不会静默丢弃')
    if (f.legend_location != 'best' or f.legend_frame or f.x_major_step is not None
            or f.y_major_step is not None or f.minor_divisions):
        raise ValueError('可编辑 PPTX 尚未映射自定义图例/刻度；请用四格式图像导出，不会静默丢弃')
    if f.axis_sides is not None or f.layout_mode!='source' or f.label_wrap:
        raise ValueError('可编辑PPTX尚未映射独立轴与自动排版；请导出图像')
    decks = Presentation(); decks.slide_width = Mm(f.width_mm + 20); decks.slide_height = Mm(f.height_mm + 20)
    slide = decks.slides.add_slide(decks.slide_layouts[6]); chart_data = LiteralData()
    datasets = {d.id: d for d in project.datasets}
    for s in visible:
        series = chart_data.add_series(s.label); columns = datasets[s.dataset].columns
        for x, y in zip(columns[s.x], columns[s.y]): series.add_data_point(x, y)
    chart = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER_LINES_NO_MARKERS,
                                   Mm(10), Mm(10), Mm(f.width_mm), Mm(f.height_mm), chart_data).chart
    chart.has_title = bool(f.title)
    if chart.has_title: chart.chart_title.text_frame.text = f.title
    chart.has_legend = f.legend
    if f.legend: chart.legend.position = XL_LEGEND_POSITION.BOTTOM; chart.legend.include_in_layout = False
    for axis, title, limits in ((chart.category_axis, f.xlabel, f.xlim), (chart.value_axis, f.ylabel, f.ylim)):
        axis.has_title = bool(title)
        if title: axis.axis_title.text_frame.text = title
        axis.has_major_gridlines = f.grid
        axis.major_tick_mark = {'in': XL_TICK_MARK.INSIDE, 'out': XL_TICK_MARK.OUTSIDE,
                                'inout': XL_TICK_MARK.CROSS}[f.tick_direction]
        axis.tick_labels.font.name = f.font; axis.tick_labels.font.size = Pt(f.font_size)
        if limits is not None: axis.minimum_scale, axis.maximum_scale = limits
    for native, source in zip(chart.series, visible):
        native.format.line.color.rgb = RGBColor.from_string(source.color[1:])
        native.format.line.width = Pt(source.width)
        native.format.line.dash_style = {'-': MSO_LINE_DASH_STYLE.SOLID, '--': MSO_LINE_DASH_STYLE.DASH,
                                        ':': MSO_LINE_DASH_STYLE.ROUND_DOT, '-.': MSO_LINE_DASH_STYLE.DASH_DOT}[source.line_style]
    initial = io.BytesIO(); decks.save(initial)
    import zipfile
    with zipfile.ZipFile(initial) as z:
        hashes = {n: sha(z.read(n)) for n in z.namelist()
                  if n.startswith('ppt/charts/') or n.startswith('ppt/embeddings/')}
    envelope = {'schema': 'sps.pptx/1', 'clipboard': json.loads(encode(project)), 'chart_parts': hashes,
                'limits': ['PowerPoint 使用自己的排版，字体/图例/轴线/页面边距不保证与 SPS 一致。',
                           'Excel 数值显示/编辑受其精度限制；完整原精度数值另存于 SPS 工程部件。',
                           '如在 PPT 中修改图表或工作簿，SPS 拒绝回读旧工程，避免覆盖新数据。']}
    part = Part(PackURI('/' + PART), 'application/json', decks.part.package, canonical(envelope).encode())
    decks.part.relate_to(part, REL_TYPE)
    output = io.BytesIO(); decks.save(output)
    # Open in exclusive mode; do not overwrite any existing user file.
    with path.open('xb') as stream: stream.write(output.getvalue())
    return {'schema': 'sps.pptx-export/1', 'file': path.name, 'series': len(visible),
            'project_sha256': project.fingerprint(), 'limits': envelope['limits']}


def recover(path):
    with package(path) as archive:
        if PART not in archive.namelist(): raise ValueError('PPTX 没有 SPS 可恢复工程；请使用 Origin 对象恢复入口')
        envelope = json.loads(read_part(archive, PART))
        if envelope.get('schema') != 'sps.pptx/1' or not isinstance(envelope.get('chart_parts'), dict):
            raise ValueError('SPS PPTX 工程协议无效')
        actual = {n: sha(read_part(archive, n)) for n in archive.namelist()
                  if n.startswith('ppt/charts/') or n.startswith('ppt/embeddings/')}
        if not actual or envelope['chart_parts'] != actual:
            raise ValueError('PPT 图表或数据已变化；拒绝回读可能过期的 SPS 工程，请保留当前 PPT 数据')
        return decode(canonical(envelope['clipboard']).encode())
