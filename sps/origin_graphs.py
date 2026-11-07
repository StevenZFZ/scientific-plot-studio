"""Automatic, reference-based Origin graph import; no adjacent-column guessing.

Original reader output remains in the document. Display padding means absent
row slots (None), never interpolated values or removal of scientific records.
"""
import copy
import math
import re
from pathlib import Path
from .model import Project,Dataset,Series,FigureSpec,Annotation,GraphPage,GraphLayer


def source_text(value,issues):
    raw=bytes.fromhex(value or '')
    try:return raw.decode('utf-8').rstrip('\0')
    except UnicodeDecodeError:
        try:
            result=raw.decode('gb18030');issues.append('旧版文字按GB18030显示；源编码需核实，原始字节保留。');return result
        except UnicodeDecodeError:
            issues.append('文字编码未解出，保留原始字节。');return '[未解码文字]'


def plain_text(value,issues):
    value=value.replace('\r\n','\n').replace('\r','\n')
    value=value.replace('\\+(o)','°').replace('\\+(O)','°')
    value=re.sub(r'\\x\(([0-9a-fA-F]{4,6})\)',lambda m:chr(int(m[1],16))if int(m[1],16)<=0x10ffff else m[0],value)
    sub=str.maketrans('0123456789+-()','₀₁₂₃₄₅₆₇₈₉₊₋₍₎')
    sup=str.maketrans('0123456789+-()','⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾')
    value=re.sub(r'\\-\(([0-9+() -]+)\)',lambda m:m[1].translate(sub),value)
    value=re.sub(r'\\\+\(([0-9+() -]+)\)',lambda m:m[1].translate(sup),value)
    if re.search(r'\\[a-zA-Z]+\(',value):issues.append('部分Origin富文本控制码未映射，保留可读内容及原记录。')
    value=re.sub(r'\\[biu]\(([^()]*)\)',r'\1',value)
    return value


PALETTE={0:'#000000',1:'#ff0000',2:'#00ff00',3:'#0000ff',4:'#00ffff',5:'#ff00ff',6:'#ffff00',17:'#ffffff'}


def curve_color(source,issues):
    if source.get('type_raw')==3:
        rgb=source.get('rgb_raw',[])
        if len(rgb)==3 and all(type(v)is int and 0<=v<=255 for v in rgb):return '#'+''.join(f'{v:02x}'for v in rgb)
    if source.get('type_raw')==2 and source.get('index_raw')in PALETTE:return PALETTE[source['index_raw']]
    issues.append('索引/自动/映射色未确认，显示为黑色，原色记录保留。');return '#000000'


def _columns(recovery,issues):
    result=[];raw=recovery['raw']
    if recovery['format']=='opju':
        for item in sorted(raw['datasets']+raw.get('resolved_columns',[]),key=lambda d:d['dataset_id']):
            props=item.get('metadata')or{};props={}if props.get('conflict')else props
            result.append({'id':item['dataset_id'],'book':item['book_identifier'],
                'sheet':item.get('sheet_suffix')or'1','name':item['column_identifier'],
                'data':copy.deepcopy(item['values']),'first':item.get('first_row',0),
                'long_name':props.get('long_name',''),'units':props.get('units','')})
    else:
        probe=raw['probe'];books=[(s,None)for s in probe.get('spreads',[])]
        books += [(s,e.get('name_hex',''))for e in probe.get('excels',[])for s in e.get('sheets',[])]
        for sheet,book in books:
            name=source_text(book or sheet.get('name_hex',''),issues)
            for column in sheet['columns']:
                result.append({'id':column.get('dataset_id'),'book':name,'sheet':str(column.get('sheet_raw',0)+1),
                    'name':source_text(column.get('name_hex',''),issues),'data':[source_text(v['text_hex'],issues)if isinstance(v,dict)and'text_hex'in v else v for v in column['data']],
                    'first':column.get('begin_row_raw',0),
                    'long_name':source_text(column.get('long_name_hex',''),issues),
                    'units':source_text(column.get('units_hex',''),issues)})
    names=set()
    for column in result:
        column['key']=f"{column['book']}@{column['sheet']}!{column['name']}"
        if column['key']in names:raise ValueError('读取结果含重复数据标识，不能自动绑定')
        names.add(column['key'])
        column['is_text']=any(isinstance(v,str)and v not in('','--')for v in column['data'])
        column['usable']=bool(column['data'])and all(v is None or isinstance(v,str)or type(v)in(int,float)and math.isfinite(v)for v in column['data'])
        if not column['is_text']:
            column['plot_data']=[None if v in('','--')else v for v in column['data']]
        else:column['plot_data']=column['data'][:]
        if column['plot_data']!=column['data']:issues.append(f"{column['key']}的空文本/--仅在数值显示中作为缺口，原单元格保留。")
    return result


def resolve_reference(columns,curve,axis,modern,issues):
    if modern or curve.get(axis+'_dataset_id')is not None:
        ident=curve.get(axis+'_dataset_id');found=[c for c in columns if c['id']==ident]
    else:
        ybook=source_text(curve.get('data_name_hex',''),issues)
        book=source_text(curve.get('x_data_name_hex',''),issues)or ybook if axis=='x'else ybook
        if book.startswith(('T_','E_')):book=book[2:]
        name=source_text(curve.get(axis+'_column_hex',''),issues)
        found=[c for c in columns if c['book']==book and c['name']==name]
    if len(found)!=1:raise ValueError(f'{axis.upper()}列引用未唯一解析（匹配{len(found)}项），没有猜配')
    if not found[0]['usable']or axis=='y'and found[0]['is_text']:raise ValueError(f"{axis.upper()}列不是可绘制的数值/行标签：{found[0]['key']}")
    return found[0]


def _label(column):
    title=column['long_name']or column['name']
    return title+(f" ({column['units']})"if column['units']else'')


def _font(figure,dataset):
    from .render import font_info
    texts=Project(figure=figure,datasets=[dataset]if dataset else[])
    for family in ('DejaVu Sans','Arial Unicode MS','PingFang SC','Heiti SC'):
        figure.font=family
        try:font_info(texts);return family
        except ValueError:continue
    raise ValueError('本机没有覆盖原始标签的字体；请安装对应字体，未静默删字')


def reconstruct_graphs(recovery):
    """Build every recognized source graph in physical order, including failures."""
    modern=recovery['format']=='opju';raw=recovery['raw']
    graphs=raw.get('graphs',[])if modern else raw['probe'].get('graphs',[])
    if not graphs:raise ValueError('读取器未恢复图页结构；保留数据工作台，不按列顺序虚构原图')
    issues=[];columns=_columns(recovery,issues);usable=[c for c in columns if c['usable']]
    if len(usable)==1:
        # The strict legacy model needs two columns; a graph with X and Y
        # referencing the same column uses the same exact values under two keys.
        usable=usable+[dict(usable[0],key=usable[0]['key']+' [same source]')]
    rows=max((len(c['data'])for c in usable),default=0)
    if rows*len(usable)>10_000_000:raise ValueError('自动图形显示矩阵过大；请用原始数据工作台显式选择')
    values={c['key']:c['plot_data']+[None]*(rows-len(c['data']))for c in usable}
    digest=raw.get('source_sha256','')if modern else raw['source']['sha256']
    dataset=Dataset('origin_values',recovery['filename'],values,source=recovery['filename'],source_sha256=digest,allow_missing=True,text_columns=[c['key']for c in usable if c['is_text']])if usable else None
    pages=[];bindings=[]
    for gi,graph in enumerate(graphs):
        page_issues=[];name=source_text(graph.get('name_hex',''),page_issues)or f'Graph {gi+1}'
        long_name=source_text(graph.get('label_hex',''),page_issues).strip()
        mode=graph.get('title_mode_raw',2)
        caption=long_name if mode==1 and long_name else f'{name} ({long_name})'if mode==0 and long_name else name
        width,height=graph.get('width_raw',0),graph.get('height_raw',0);dpi=graph.get('dpi_raw',[0,0])
        physical=[v/d*25.4 if v and d else 0 for v,d in zip((width,height),dpi)]
        if len(physical)!=2 or not all(40<=v<=600 for v in physical):
            physical=[160,110];page_issues.append('源物理尺寸未可靠解析，当前画布160×110mm，原尺寸记录保留。')
        layers=[]
        for li,source in enumerate(graph.get('layers',[])):
            prefix=f'g{gi+1}_l{li+1}';layer_issues=[]
            f=FigureSpec(width_mm=physical[0],height_mm=physical[1],title='',legend=bool(source.get('legend_hex')))
            axes=[source.get('x_axis',{}),source.get('y_axis',{})]
            for axis,a in zip(('x','y'),axes):
                if a.get('tick_value_type_raw',0)not in(0,1,7,9):
                    layer_issues.append(f'{axis.upper()}轴的日期/特殊刻度标签类型未映射，原记录保留。')
                scale=a.get('scale_raw',0)
                if scale in(0,1):setattr(f,axis+'scale','log'if scale==1 else'linear')
                else:layer_issues.append(f'{axis.upper()}轴类型{scale}未映射，暂用线性显示。')
                bounds=[a.get('min'),a.get('max')]
                if all(type(v)in(int,float)and math.isfinite(v)for v in bounds)and bounds[0]<bounds[1]and(scale!=1 or bounds[0]>0):setattr(f,axis+'lim',bounds)
                else:layer_issues.append(f'{axis.upper()}轴范围无效，当前自动范围。')
                step=a.get('step')
                if scale==0 and type(step)in(int,float)and step>0 and getattr(f,axis+'lim')and(bounds[1]-bounds[0])/step<1000:setattr(f,axis+'_major_step',step)
                size=a.get('title_size_raw')
                if type(size)in(int,float)and 5<=size<=96:setattr(f,axis+'label_size',size)
            size=axes[0].get('tick_font_size_raw')
            if type(size)in(int,float)and 5<=size<=96:f.tick_size=size;f.font_size=min(48,size)
            thickness=axes[0].get('axis_width_raw')
            if type(thickness)in(int,float)and .1<=thickness<=5:f.axis_width=thickness
            f.tick_direction={1:'out',2:'in',3:'inout'}.get(axes[0].get('tick_direction_raw'),'in')
            f.box=bool(axes[0].get('opposite_visible',False)or axes[1].get('opposite_visible',False))
            f.grid=bool(axes[0].get('grid_visible',False)or axes[1].get('grid_visible',False))
            if axes[0].get('opposite_visible')!=axes[1].get('opposite_visible'):layer_issues.append('上下/左右轴的独立显隐尚未完全映射。')
            pairs=[];source_y={}
            for ci,curve in sorted(enumerate(source.get('curves',[])),key=lambda pair:pair[1].get('type_raw')==231):
                record={'page':gi,'layer':li,'curve':ci,'status':'unresolved','source':copy.deepcopy(curve)}
                try:
                    if graph.get('is3d')or graph.get('is_layout'):raise ValueError('3D/布局页尚未重建，保留图页及原记录')
                    kind=curve.get('type_raw')
                    if kind==231:
                        parent_ref=resolve_reference(columns,curve,'x',modern,layer_issues)
                        error_ref=resolve_reference(columns,curve,'y',modern,layer_issues)
                        parents=[s for s in f.series if source_y.get(s.id)==parent_ref['key']]
                        if len(parents)!=1:raise ValueError('误差棒的父Y引用未唯一匹配，没有按相邻顺序猜配')
                        if any(type(v)in(int,float)and v<0 for v in error_ref['plot_data']):raise ValueError('误差值含负数，未重建误差棒')
                        error_span=curve.get('row_range_raw')
                        if error_span not in(None,[0,0],parents[0].row_range):raise ValueError('误差棒与父曲线行区间不同，未隐式改变误差对应关系')
                        parents[0].y_error=error_ref['key']
                        record.update(status='bound',x=parent_ref['key'],y=error_ref['key'],parent_series=parents[0].id,role='y_error')
                        bindings.append(record);continue
                    if kind not in(200,201,202,203):raise ValueError(f'图型{kind}尚未映射，未用折线冒充')
                    x=resolve_reference(columns,curve,'x',modern,layer_issues);y=resolve_reference(columns,curve,'y',modern,layer_issues)
                    if x['is_text']:
                        xtype=axes[0].get('tick_value_type_raw');label_ref=axes[0].get('tick_dataset_id')
                        if xtype not in(1,7)or f.xscale!='linear':
                            raise ValueError('文本X缺少明确的原始行标签轴引用，未猜测分类顺序')
                        if label_ref is not None:
                            label_columns=[c for c in columns if c['id']==label_ref]
                            if len(label_columns)!=1:raise ValueError('行标签轴的数据引用未唯一解析')
                            label_column=label_columns[0]
                        else:label_column=x
                        tick_pairs=[(i+1,plain_text(str(v),layer_issues))for i,v in enumerate(label_column['plot_data'])if v is not None]
                        f.xtick_dataset=dataset.id;f.xtick_column=label_column['key']
                        if len(tick_pairs)>5000:raise ValueError('分类行标签超过显示预算')
                        f.xtick_values=[v for v,_ in tick_pairs];f.xtick_labels=[v for _,v in tick_pairs]
                    series=Series(f'{prefix}_c{ci+1}',dataset.id,x['key'],y['key'],label=_label(y),
                        kind={200:'line',201:'scatter',202:'line',203:'bar'}[kind],visible=not curve.get('hidden',False),
                        color=curve_color(curve.get('fill_color',curve.get('line_color',{}))if kind==203 else curve.get('line_color',{}),layer_issues))
                    span=curve.get('row_range_raw')
                    if isinstance(span,list)and len(span)==2 and all(type(v)is int for v in span)and 0<=span[0]<span[1]<=rows:
                        series.row_range=span[:]
                    elif span not in(None,[0,0]):layer_issues.append(f'曲线{ci+1}源行范围未映射，当前显示完整已恢复列。')
                    if kind in(201,202):series.marker='o';layer_issues.append(f'曲线{ci+1}符号形状未校准，显示圆符号。')
                    if kind==203:layer_issues.append(f'曲线{ci+1}柱宽/填充图案和边框未完整映射，保留原记录。')
                    line=curve.get('line_style_raw');series.line_style={0:'-',1:'--',2:':',3:'-.'}.get(line,'-')
                    if line not in(0,1,2,3):layer_issues.append(f'曲线{ci+1}线型未映射，暂用实线。')
                    if curve.get('line_connect_raw')!=1 and kind in(200,202):raise ValueError('非直连插值语义尚未映射，未改变插值方式')
                    sw=curve.get('line_width_raw')
                    if type(sw)in(int,float)and .1<=sw<=10:series.width=sw
                    else:layer_issues.append(f'曲线{ci+1}线宽未映射，暂用默认值。')
                    sz=curve.get('symbol_size_raw')
                    if type(sz)in(int,float)and 1<=sz<=25:series.marker_size=sz
                    for axis,col in(('x',x),('y',y)):
                        if getattr(f,axis+'scale')=='log'and any(v is not None and v<=0 for v in col['data']):
                            layer_issues.append(f'曲线{ci+1}{axis.upper()}非正数保留在数据中，对数显示为缺口。')
                    f.series.append(series);pairs.append((x,y));source_y[series.id]=y['key']
                    record.update(status='bound',x=x['key'],y=y['key'],row_range=series.row_range,source_rows=[len(x['data']),len(y['data'])])
                except ValueError as error:layer_issues.append(f'曲线{ci+1}：{error}');record['reason']=str(error)
                bindings.append(record)
            for axis,a,col_index in(('x',axes[0],0),('y',axes[1],1)):
                title=source_text(a.get('title_hex',''),layer_issues)
                if '%(?'+axis.upper()+')'in title and pairs:title=title.replace('%(?'+axis.upper()+')',_label(pairs[0][col_index]))
                if '%('in title:layer_issues.append(f'{axis.upper()}轴动态标签未完全展开。')
                setattr(f,axis+'label',plain_text(title,layer_issues))
            if type(source.get('legend_size_raw'))in(int,float)and 5<=source['legend_size_raw']<=96:f.legend_size=source['legend_size_raw']
            legend=source_text(source.get('legend_hex',''),layer_issues)
            legend_lines=legend.replace('\r\n','\n').splitlines()
            for index,line in enumerate(legend_lines):
                m=re.search(r'\\l\((\d+)\)\s*(.*)',line)
                if m and 1<=int(m[1])<=len(f.series):
                    k=int(m[1])-1;value=m[2]
                    for n,(_,y)in enumerate(pairs,1):value=value.replace(f'%({n})',_label(y))
                    if '%('not in value:f.series[k].label=plain_text(value,layer_issues)
                    else:layer_issues.append('动态图例未完全展开；保留对应Y列标签。')
            rectangle=source.get('client_rect');rect=None
            if rectangle and width and height:
                l,t,r,b=rectangle;candidate=[l/width,1-b/height,(r-l)/width,(b-t)/height]
                if min(candidate)>=0 and candidate[2]>0 and candidate[3]>0 and candidate[0]+candidate[2]<=1.000001 and candidate[1]+candidate[3]<=1.000001:rect=candidate
            if rect is None:layer_issues.append('图层几何未恢复，使用默认轴区；原坐标保留。')
            for ti,item in enumerate(source.get('texts',[])):
                value=plain_text(source_text(item.get('text_hex',''),layer_issues),layer_issues)
                if value and rectangle and item.get('rect_raw')and '%('not in value:
                    left,top,right,bottom=rectangle;al,at,_,_=item['rect_raw']
                    px=(al-left)/(right-left);py=1-(at-top)/(bottom-top)
                    if 0<=px<=1 and 0<=py<=1:
                        sz=item.get('font_size_raw',11);sz=sz if 5<=sz<=48 else 11
                        f.annotations.append(Annotation(f'{prefix}_t{ti+1}',value,px,py,sz,curve_color(item.get('color',{}),layer_issues)))
                    else:layer_issues.append('轴区外文本坐标尚未映射，原文保留。')
            for kind in('line_count','figure_count','bitmap_count'):
                if source.get(kind):layer_issues.append(f"{source[kind]}个{kind}对象未映射，保留原记录。")
            family=_font(f,dataset);layer_issues.append(f'字体族未解出，当前显示{family}；不是原字体确认。')
            layer_issues.append('线宽/虚线后端映射尚需Origin原图校准。')
            layers.append(GraphLayer(prefix,source.get('name')or f'图层 {li+1}',f,rect,
                axes_visible=bool(axes[0].get('visible',True)or axes[1].get('visible',True)),issues=list(dict.fromkeys(layer_issues))))
        if not layers:layers=[GraphLayer(f'g{gi+1}_empty','未解析图层',FigureSpec(width_mm=physical[0],height_mm=physical[1]),issues=['源图层未解析；未虚构曲线。'])]
        pages.append(GraphPage(f'g{gi+1}',caption,layers,gi,list(dict.fromkeys(page_issues))))
    project=Project(name=Path(recovery['filename']).stem,datasets=[dataset]if dataset else[],pages=pages,
        origin={'recovery':copy.deepcopy(recovery),'bindings':sorted(bindings,key=lambda b:(b['page'],b['layer'],b['curve'])),'issues':list(dict.fromkeys(issues)),
                'ordering':'stored graph/window order; project-explorer folder sorting unverified',
                'display_matrix':'Absent row slots padded with None; original capacity/values remain in recovery.'})
    project.audit.append({'kind':'origin_reference_graph_import','graphs':len(pages),
        'bound_curves':sum(b['status']=='bound'for b in bindings),'unresolved_curves':sum(b['status']!='bound'for b in bindings),
        'source_sha256':digest,'format':recovery['format'],'limits':'部分字段恢复；不是Origin原图像素保真验收。'})
    project.validate()
    from .model import canonical
    if len(canonical(project.to_dict()).encode('utf-8'))>45_000_000:
        raise ValueError('自动图页工程超过可往返的45MB预算；请在数据工作台明确选择子集')
    return project


def read_project(path,probe=None,decoder=None):
    from .origin_reader import OriginProject
    recovery=OriginProject(path,legacy_probe=probe,opju_decoder=decoder,allow_graph_only=True).to_dict()
    try:return {'project':reconstruct_graphs(recovery),'recovery':recovery,'error':None}
    except ValueError as error:return {'project':None,'recovery':recovery,'error':str(error)}
