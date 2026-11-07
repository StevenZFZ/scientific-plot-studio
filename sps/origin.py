"""Optional legacy OPJ inspection and evidence-bounded style migration.

External readers are explicit executables, never Python imports into the core.
Reports contain styles/counts only, not recovered worksheet values or scripts.
"""
from __future__ import annotations
import copy
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

from .model import canonical, read_json, write_json, Project, Dataset, Series, FigureSpec
from .commands import run_operations

SCHEMA = 'sps.origin-analysis/1'
PROFILE_SCHEMA = 'sps.origin-profile/1'
LINE_STYLES = {0: '-', 1: '--', 2: ':', 3: '-.'}
PLOT_NAMES = {200: '折线', 201: '散点', 202: '线与符号', 203: '柱状', 231: 'Y 误差棒'}
REGULAR_COLORS = {0:'#000000', 17:'#ffffff'}
LIMITS = ['读取结果尚未与 Origin 本体逐项比对，不能证明原图保真。',
          '仅提取支持的逐层样式；不迁移数据、轴含义、范围、图层布局或分析结果。',
          '字体族、物理尺寸、动态图例、注释、透明度与精确符号形状未映射。',
          '线宽按读取器数值近似对应 SPS pt，虚线图案为后端近似；仍需原图对照校准。']


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def seal(report):
    report = copy.deepcopy(report)
    report.pop('digest', None)
    report['digest'] = hashlib.sha256(canonical(report).encode()).hexdigest()
    return report


def validate_report(report):
    if not isinstance(report,dict) or report.get('schema') not in (SCHEMA, PROFILE_SCHEMA):
        raise ValueError('不是受支持的 Origin 风格报告')
    if report.get('digest') != seal(report)['digest']:
        raise ValueError('风格报告摘要不一致，请重新分析')
    return report


def raw_text(value):
    if not isinstance(value,str) or len(value)>20000:
        raise ValueError('Origin 文字字段无效')
    try: b=bytes.fromhex(value)
    except ValueError as error: raise ValueError('Origin 原始文字编码无效') from error
    try: return b.decode('utf-8')
    except UnicodeDecodeError: return '[原始字节] '+value[:120]


def mapped_curve(curve,index):
    if not isinstance(curve,dict): raise ValueError('曲线对象无效')
    properties, issues = {}, []
    kind=curve.get('type_raw')
    if type(kind) is not int: raise ValueError('曲线类型无效')
    if kind not in (200,201,202,203):
        return {'index':index,'plot_type_raw':kind,'plot_type':PLOT_NAMES.get(kind,f'未支持类型 {kind}'),
                'style':{},'issues':['该图型的样式关系尚未映射，保持目标曲线不变。']}
    col=curve.get('line_color',{})
    if col.get('type_raw')==3:
        rgb=col.get('rgb_raw')
        if isinstance(rgb,list) and len(rgb)==3 and all(type(v) is int and 0<=v<=255 for v in rgb):
            properties['color']='#'+''.join(f'{v:02x}' for v in rgb)
        else: issues.append('自定义 RGB 无效，未迁移颜色。')
    elif col.get('type_raw')==2 and col.get('index_raw') in REGULAR_COLORS:
        properties['color']=REGULAR_COLORS[col['index_raw']]
    else: issues.append('索引/自动/映射颜色尚未可靠解析，未迁移颜色。')
    width=curve.get('line_width_raw')
    if type(width) in (int,float) and math.isfinite(width) and .1<=width<=10:
        properties['width']=float(width)
    else: issues.append('源线宽不在已验证范围内，未迁移。')
    line=curve.get('line_style_raw')
    if type(line) is int and line in LINE_STYLES: properties['line_style']=LINE_STYLES[line]
    else: issues.append('源线型尚未映射，未迁移。')
    if curve.get('line_connect_raw')!=1:
        issues.append('源连接方式不是直连；本次只迁移格式，不改变目标连接或数据。')
    if kind in (201,202,203):
        issues.append('源符号/填充尚未映射；本次仅保留可用描边属性。')
    return {'index':index,'plot_type_raw':kind,'plot_type':PLOT_NAMES.get(kind,str(kind)),
            'style':properties,'issues':issues}


def analyze_probe(data, source=None):
    if not isinstance(data,dict) or data.get('schema')!='sps.experimental.origin-probe/1':
        raise ValueError('探针输出版本不支持')
    graphs=data.get('graphs')
    if not isinstance(graphs,list) or len(graphs)>512: raise ValueError('图形列表无效或过大')
    layers=[]
    for gi,graph in enumerate(graphs):
        if not isinstance(graph,dict) or not isinstance(graph.get('layers'),list) or len(graph['layers'])>128:
            raise ValueError('图层结构无效')
        for li,layer in enumerate(graph['layers']):
            curves=layer.get('curves')
            if not isinstance(curves,list) or len(curves)>512: raise ValueError('曲线列表无效')
            issues=list(LIMITS)
            if len(graph['layers'])>1: issues.append(f'该图有 {len(graph["layers"])} 层；当前选择只代表一层，其他层未迁移。')
            if graph.get('is3d') or graph.get('is_layout'):issues.append('3D/布局页不提供模板转换。')
            mapped=[mapped_curve(c,i) for i,c in enumerate(curves)]
            layers.append({'id':f'g{gi+1}:l{li+1}','graph_index':gi,'layer_index':li,
                           'graph_name':raw_text(graph.get('name_hex','')) or f'Graph {gi+1}',
                           'graph_layer_count':len(graph['layers']),
                           'is3d':bool(graph.get('is3d')),'is_layout':bool(graph.get('is_layout')),
                           'source_template_name':raw_text(graph.get('template_name_hex','')),
                           'source_legend_rule':raw_text(layer.get('legend_hex','')),
                           'axis_observations':{axis:{'scale_raw':layer.get(axis,{}).get('scale_raw'),
                                                    'tick_font_size_raw':layer.get(axis,{}).get('tick_font_size_raw')}
                                                for axis in ('x_axis','y_axis')},
                           'curves':mapped,'issues':issues})
    observations=[c for l in layers for c in l['curves']]
    stats=style_statistics(layers)
    report={'schema':SCHEMA,'source':source or {'name':'probe output','sha256':''},
            'reader':{'name':'optional external liborigin probe','version':str(data.get('liborigin','unknown')),
                      'scope':'legacy OPJ partial inspection; not Origin verified'},
            'counts':{'graphs':len(graphs),'layers':len(layers),'curves':len(observations),
                      'multi_layer_graphs':sum(len(g['layers'])>1 for g in graphs)},
            'statistics':stats,'layers':layers,'limits':list(LIMITS)}
    return seal(report)


def style_statistics(layers):
    curves=[c for l in layers for c in l['curves']]
    stats={}
    for key in ('color','width','line_style'):
        values=Counter(str(c['style'][key]) for c in curves if key in c['style'])
        stats[key]={'observed':sum(values.values()),'total':len(curves),
                    'frequencies':[{'value':k,'count':n} for k,n in values.most_common()]}
    types=Counter(c['plot_type'] for c in curves)
    stats['plot_types']=[{'value':k,'count':v} for k,v in types.most_common()]
    font=Counter(str(l['axis_observations'][a]['tick_font_size_raw']) for l in layers for a in ('x_axis','y_axis')
                 if l['axis_observations'][a]['tick_font_size_raw'] is not None)
    stats['axis_tick_sizes_raw']=[{'value':k,'count':v} for k,v in font.most_common()]
    return stats


def inspect(path, probe):
    path,probe=Path(path).resolve(strict=True),Path(probe).resolve(strict=True)
    if not probe.is_file(): raise ValueError('请选择已安装的独立 Origin 探针程序')
    if path.stat().st_size>50_000_000: raise ValueError('Origin 样本超过 50 MB 限制')
    with path.open('rb') as f:header=f.read(80)
    if header.startswith(b'CPYUA '): raise ValueError('OPJU 尚不受本地读取器支持；需要可选 Windows Origin 适配。')
    if path.suffix.lower()!='.opj' or not header.startswith(b'CPYA '):
        raise ValueError('当前读取器只支持 CPYA 签名的旧 OPJ；OTP/OTPU/OTH 未实现。')
    before=file_hash(path)
    with tempfile.TemporaryDirectory(prefix='sps-origin-') as directory:
        directory=Path(directory);snapshot=directory/'source.opj';target=directory/'probe.json'
        snapshot.write_bytes(path.read_bytes())
        if file_hash(snapshot)!=before:raise ValueError('读取时源文件发生变化')
        try:
            result=subprocess.run([str(probe),str(snapshot),str(target)],cwd=directory,
                                  capture_output=True,timeout=30,check=False)
        except subprocess.TimeoutExpired as e: raise ValueError('Origin 读取超时；未生成分析结果') from e
        if result.returncode:raise ValueError(f'独立读取器失败（退出码 {result.returncode}）；未导入工程')
        if file_hash(snapshot)!=before or file_hash(path)!=before:raise ValueError('读取前后文件摘要变化，结果拒绝')
        data=read_json(target)
        report=analyze_probe(data,{'name':path.name,'sha256':before,'bytes':path.stat().st_size})
        report['reader']['executable_sha256']=file_hash(probe)
        return seal(report)


def profile(paths, probe):
    reports=[];files=[]
    for path in sorted({str(Path(p).resolve()) for p in paths}):
        try:
            report=inspect(path,probe)
            reports.append(report)
            files.append({'name':Path(path).name,'sha256':report['source']['sha256'],'status':'partial_style_analyzed'})
        except (ValueError,OSError) as e:
            files.append({'name':Path(path).name,'status':'unsupported_or_failed','reason':str(e)})
    layers=[layer for report in reports for layer in report['layers']]
    return seal({'schema':PROFILE_SCHEMA,'files':files,'analyses':reports,
                 'counts':{'files':len(files),'analyzed':len(reports),'unsupported_or_failed':len(files)-len(reports),
                           'graphs':sum(r['counts']['graphs'] for r in reports),'layers':len(layers),
                           'curves':sum(len(l['curves']) for l in layers)},
                 'statistics':style_statistics(layers),'limits':list(LIMITS)+['频率是这组样本的观测分布，不能自动认定为个人偏好或投稿规范。']})


def layer_style(report, layer_id):
    validate_report(report)
    if report['schema']!=SCHEMA:raise ValueError('请从单个工程选择图层')
    layer=next((l for l in report['layers'] if l['id']==layer_id),None)
    if layer is None:raise ValueError('图层不存在')
    palette=[copy.deepcopy(c['style']) for c in layer['curves']]
    if not any(palette):raise ValueError('所选图层没有可迁移的格式')
    style={'schema':'sps.style/1','name':f'Origin 部分风格 · {layer["graph_name"]} / {layer_id}',
           'source_project':report['source']['sha256'],'figure':{},'series':palette}
    # Use the same validation used by all clients, rather than trusting report fields.
    run_operations(Project(datasets=[Dataset('check','check',{'x':[1.,2.],'y':[2.,3.]})],
                           figure=FigureSpec(
                               series=[Series('curve','check','x','y')])),[{'op':'apply_style','style':style}])
    return style


def layer_template(report, layer_id):
    from .templates import NativeTemplate,PlotSlot
    style=layer_style(report,layer_id)
    layer=next(l for l in report['layers'] if l['id']==layer_id)
    if layer['is3d'] or layer['is_layout'] or not 1<=len(layer['curves'])<=32:
        raise ValueError('3D、布局页或超出 1–32 槽位的图层暂不能生成部分模板')
    if any(c['plot_type_raw']!=200 for c in layer['curves']):
        raise ValueError('部分模板首版仅支持纯折线层；符号、误差和柱图关系需要后续映射')
    issues=layer['issues']+sorted({i for c in layer['curves'] for i in c['issues']})
    template=NativeTemplate('origin_'+report['digest'][:12]+'_'+layer_id.replace(':','_'),
                            style['name']+' · 部分模板',
                            {'title':'{{title}}','xlabel':'{{x_label}}','ylabel':'{{y_label}}'},
                            [PlotSlot(f'plot_{i+1}',f'源曲线 {i+1}',{'kind':'line',**c['style']}) for i,c in enumerate(layer['curves'])],
                            schema='sps.template/2',
                            description='仅所选层部分格式；未映射字段使用 SPS 默认值；新数据显式绑定。\n'+'\n'.join(issues),
                            source={'kind':'origin_partial','name':report['source']['name'],
                                    'source_sha256':report['source']['sha256'],'mapping_report_hash':report['digest']})
    return template.validate()


def markdown(report):
    validate_report(report)
    counts=report['counts']
    title='Origin 样本风格总结' if report['schema']==PROFILE_SCHEMA else 'Origin 工程风格分析 · '+report['source']['name']
    lines=['# '+title,'','性质：基于可读取属性的本地统计，不是 AI 结论，也不证明原图保真。','',
           f"图形 {counts['graphs']} · 图层 {counts['layers']} · 曲线 {counts['curves']}",'']
    if report['schema']==PROFILE_SCHEMA:
        lines += [f"文件 {counts['files']}：部分分析 {counts['analyzed']}，不支持/失败 {counts['unsupported_or_failed']}。",'']
    for key,name in [('color','可识别描边颜色'),('width','线宽观测值'),('line_style','近似线型')]:
        stat=report['statistics'][key]
        lines += [f"## {name}（可识别 {stat['observed']} / {stat['total']} 条）",'']
        lines += [f"- {entry['value']}：{entry['count']} 条" for entry in stat['frequencies'][:16]] or ['- 无可靠观测']
        lines.append('')
    lines += ['## 图形类型','']+[f"- {e['value']}：{e['count']} 条" for e in report['statistics']['plot_types']]
    lines += ['','## 限制与未映射项','']+['- '+s for s in report['limits']]
    if report['schema']==SCHEMA:
        lines += ['','## 逐层清单','']
        for layer in report['layers']:
            lines += [f"- {layer['id']} · {layer['graph_name']} · {len(layer['curves'])} 条曲线 · 原图 {layer['graph_layer_count']} 层"]
            for issue in sorted({s for c in layer['curves'] for s in c['issues']}):lines.append('  - '+issue)
    else:
        lines += ['','## 文件状态','']+[f"- {f['name']}：{f['status']}"+(' · '+f['reason'] if 'reason' in f else '') for f in report['files']]
    return '\n'.join(lines)+'\n'


def style_observations(report):
    """Anonymous aggregate for an AI context; excludes filenames, text and ranges."""
    validate_report(report)
    return {'schema':'sps.style-observations/1',
            'counts':{k:v for k,v in report['counts'].items() if k in ('files','analyzed','unsupported_or_failed','graphs','layers','curves')},
            'statistics':{k:copy.deepcopy(report['statistics'][k]) for k in ('color','width','line_style')}}
