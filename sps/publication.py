"""Source-backed typography presets; SPS layout choices are explicitly separate.

Never edits data, ranges, curve properties, source names or Origin recovery.
"""
import copy
from pathlib import Path
from .model import canonical

VERIFIED='2026-10-21'
PROFILES={
 'nature':{'name':'Nature · 研究图','font_size':7,'range':[5,7],'widths':[89,183],
  'source':'https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/',
  'official':'研究图最终宽89/183mm，文字5–7pt；标准无衬线字体。','fonts':['Arial','Helvetica'],
  'choices':'SPS选择7pt统一字号、四边框和左下刻度；不是期刊指定的唯一轴样式。'},
 'communications_materials':{'name':'Communications Materials','font_size':8,'range':[8,12],'widths':[89,183],
  'source':'https://www.nature.com/commsmat/submit/formatting-guidelines',
  'official':'Helvetica/Arial 8–12pt，图内字号差异尽量小；线至少0.3pt。','fonts':['Arial','Helvetica'],
  'choices':'SPS选择8pt；89/183mm为本软件版面选择，并非该指南明确指定的宽度。'},
 'nano_letters':{'name':'Nano Letters · ACS','font_size':8,'range':[4.5,None],'widths':[84.6666666667,177.8],
  'source':'https://researcher-resources.acs.org/publish/author_guidelines?coden=nalefd',
  'official':'单栏至240pt，双栏300–504pt；文字至少4.5pt，线至少0.5pt；Helvetica/Arial适用。','fonts':['Arial','Helvetica'],
  'choices':'SPS选择8pt与单/双栏上限宽度；8pt不是ACS硬性要求。'},
 'elsevier':{'name':'Elsevier · 通用建议','font_size':7,'range':[7,None],'widths':[90,190],
  'source':'https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing',
  'official':'通用建议普通字7pt、上下标不小于6pt，单/双栏90/190mm；具体期刊指南优先。','fonts':[],
  'choices':'这是出版商通用建议。SPS7pt的数学上下标仍会更小，需最终单独核对6pt下限；不代表完整合规。'},
}


def framed_sides():
    return {side:{'spine':True,'ticks':side in('bottom','left'),'labels':side in('bottom','left')}for side in('bottom','top','left','right')}


def effective_sides(figure):
    if figure.axis_sides is not None:return copy.deepcopy(figure.axis_sides)
    return {side:{'spine':side in('bottom','left')or figure.box,'ticks':side in('bottom','left')or figure.box,'labels':side in('bottom','left')}for side in('bottom','top','left','right')}


def active_layers(layers):
    return [i for i,layer in enumerate(layers)if layer.axes_visible or layer.figure.annotations or any(s.visible for s in layer.figure.series)]


def apply_profile(project,profile,size,scope,font):
    if profile not in PROFILES or size not in('single','double')or scope not in('page','all'):raise ValueError('期刊/栏宽/范围无效')
    if not isinstance(font,str)or not font:raise ValueError('请明确选择已安装字体')
    before=canonical([d.__dict__ for d in project.datasets]);context=project.context
    preset=PROFILES[profile];width=preset['widths'][size=='double'];pt=preset['font_size']
    targets=range(len(project.pages))if project.pages and scope=='all'else[context[0]]
    for pi in targets:
        layers=project.pages[pi].layers if project.pages else []
        figures=[l.figure for l in layers]if layers else[project.figure]
        active=active_layers(layers)if layers else[0]
        simple=len(active)==1
        base=figures[0];height=width*base.height_mm/base.width_mm
        height=max(50,min(height,170)) # SPS layout policy; not a journal-specific universal requirement.
        for fi,f in enumerate(figures):
            f.width_mm=width;f.height_mm=height;f.font=font;f.font_size=pt
            f.xlabel_size=f.ylabel_size=f.tick_size=f.legend_size=pt
            f.axis_width=.8;f.tick_direction='in';f.label_wrap=True
            if simple and fi==active[0]:
                f.axis_sides=framed_sides();f.box=True;f.layout_mode='auto'
                f.x_major_step=f.y_major_step=None;f.minor_divisions=0
            # Multiple layers may implement a second scale or inset; preserve
            # their source geometry and side placement until explicitly reviewed.
            for annotation in f.annotations:annotation.size=pt
        if project.pages:
            if simple:layers[active[0]].rect=None
            else:
                notice='期刊规范化保留多层位置/轴侧/刻度设置，避免覆盖双轴或插图；请逐层检查。'
                if notice not in project.pages[pi].issues:project.pages[pi].issues.append(notice)
    project.select_context(*context)
    if canonical([d.__dict__ for d in project.datasets])!=before:raise ValueError('规范化改变了数据，已拒绝')
    project.validate()
    # Explicitly reject unavailable fonts instead of silently changing families.
    from .render import font_info
    from .model import Project
    for pi in targets:
        figures=[l.figure for l in project.pages[pi].layers]if project.pages else[project.figure]
        for f in figures:font_info(Project(figure=f,datasets=project.datasets))
    return project


def operation(profile='nature',size='single',scope='all',font='Arial'):
    return {'op':'normalize_publication','profile':profile,'size':size,'scope':scope,'font':font}


def wrap_label(value,budget,renderer,family,size):
    """Wrap only at existing whitespace using measured glyph widths. Keep source text."""
    from matplotlib.font_manager import FontProperties
    prop=FontProperties(family=family,size=size)
    result=[]
    for paragraph in value.split('\n'):
        words=paragraph.split();line=''
        for word in words:
            candidate=(line+' '+word).strip()
            if line and renderer.get_text_width_height_descent(candidate,prop,'$'in candidate)[0]>budget:
                result.append(line);line=word
            else:line=candidate
        result.append(line)
    return '\n'.join(result)


def readability(figure):
    """Detect adjacent drawn numeric/category tick labels overlapping. No data edits."""
    renderer=figure.canvas.get_renderer();issues=[]
    for i,ax in enumerate(figure.axes,1):
        if not ax.axison:continue
        for name,axis,limits in(('X',ax.xaxis,ax.get_xlim()),('Y',ax.yaxis,ax.get_ylim())):
            for label in('label1','label2'):
                texts=[getattr(t,label)for t in axis.get_major_ticks()if min(limits)<=t.get_loc()<=max(limits)]
                boxes=[t.get_window_extent(renderer)for t in texts if t.get_visible()and t.get_text().strip()]
                boxes.sort(key=lambda b:b.x0 if name=='X'else b.y0)
                if any(a.overlaps(b)for a,b in zip(boxes,boxes[1:])):issues.append(f'图层{i} {name}轴刻度相互重叠')
    return issues


def inspect_pages(project,dpi=100):
    from .render import preflight
    context=project.context;result=[]
    try:
        for pi in range(len(project.pages))if project.pages else[0]:
            project.select_context(pi)
            try:preflight(project,dpi);error=None
            except ValueError as e:error=str(e)
            figures=[layer.figure for layer in project.pages[pi].layers]if project.pages else[project.figure]
            thick=[s.width for f in figures for s in f.series if s.visible and s.width>f.font_size*.3]
            notes=[f'源曲线最大线宽{max(thick):g}pt，相对当前字体偏粗；已保留，请逐图检查（SPS提示）。']if thick else[]
            result.append({'page':pi,'name':project.pages[pi].name if project.pages else project.name,'passed':error is None,'error':error,'notes':notes})
    finally:project.select_context(*context)
    return result


def batch_import(sources,directory,options,probe=None,decoder=None):
    """Read each source once into new native files; report failures without guessing.

    No image export or overwrite. Successful native documents include preflight
    issues for per-page review; a failed file does not stop remaining files.
    """
    from .origin_graphs import read_project
    from .commands import Session
    from .model import save,load,write_json
    if not isinstance(sources,(list,tuple))or not 1<=len(sources)<=100:raise ValueError('一次请选择1–100份工程')
    if options.get('profile')not in PROFILES or options.get('size')not in('single','double'):raise ValueError('无效的期刊设置')
    out=Path(directory);out.mkdir(parents=True,exist_ok=False)
    report={'schema':'sps.publication-batch/1','options':options,'profile':PROFILES[options['profile']],'verified':VERIFIED,'files':[]}
    for index,source in enumerate(sources,1):
        entry={'source':Path(source).name};report['files'].append(entry)
        try:
            result=read_project(source,probe,decoder)
            if result['project']is None:raise ValueError(result['error'])
            session=Session(result['project']);session.execute([operation(**dict(options,scope='all'))],actor='publication_batch')
            p=session.project;checks=inspect_pages(p);entry.update(pages=len(p.pages),checks=checks)
            p.audit.append({'kind':'publication_checks','profile':options['profile'],'results':checks,'source':PROFILES[options['profile']]['source']})
            target=out/f'{index:03d}-{Path(source).stem}.sps.json';save(p,target)
            if load(target).to_dict()!=p.to_dict():raise ValueError('规范化工程保存重开不一致')
            entry.update(status='saved',output=target.name,roundtrip=True,requires_review=any(not c['passed']for c in checks))
        except Exception as e:entry.update(status='failed',error=str(e))
        write_json(out/'batch-report.json',report)
    return report


def display_text(value):
    """Display Unicode scripts using the chosen font's ordinary digit glyphs.

    Origin recovery retains original text. No external TeX or unit conversion;
    the Celsius compatibility glyph becomes the equivalent degree+C spelling.
    """
    import re
    sub='₀₁₂₃₄₅₆₇₈₉₊₋₍₎';sup='⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾'
    for chars,operator in ((sub,'_'),(sup,'^')):
        table=str.maketrans(chars,'0123456789+-()')
        value=re.sub('['+chars+']+',lambda m:'$'+operator+'{\\mathregular{'+m[0].translate(table)+'}}$',value)
    return value.replace('℃','°C')
