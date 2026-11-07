"""Sample-bounded OPJU graph records; original bytes and explicit dataset IDs.

The external primitive module is already hash-checked by opju_worker. These
records describe stored objects, not a pixel-identity claim against Origin.
"""
import math
import struct


def _text(data):
    return data.split(b'\0',1)[0].decode('utf-8').strip('\r\n')


def _color(raw):
    if len(raw)!=4:return {'type_raw':-1}
    if raw[3]==1:return {'type_raw':3,'rgb_raw':list(raw[:3])}
    if raw[3]==0 and raw[0]<100 or raw[3]==255 and raw[0]not in(247,252):
        return {'type_raw':2,'index_raw':raw[0]}
    return {'type_raw':-1,'raw_hex':raw.hex()}


def graph_records(data,start,records,module):
    """Retain physical record order. Never find a Y column by adjacency."""
    objects=[]
    # Some empty object bodies have fixed delimiters, not extension records.
    # Inspect each bounded RLE payload independently instead of swallowing the
    # next record as an extension. Accept only typed, size-checked signatures.
    offset=start
    while True:
        offset=data.find(b'\x80',offset)
        if offset<0:break
        pos=offset;offset+=1
        try:
            size,p=module.uint(data,pos+1)
            if not 5<=size<=4000:continue
            raw,end=module.rle_payload(data,p,size,maximum=8192)
            if len(raw)not in(195,361,405,133,159,111,515,519):continue
            extension=b''
            if len(raw)in(195,361,405,111):
                try:
                    rr,extension,_=module.object_record(data,pos,maximum=8192)
                    if rr!=raw or len(extension)>20000:extension=b''
                except (module.DecodeError,IndexError):pass
            objects.append((pos,raw,extension,end))
        except (module.DecodeError,IndexError,struct.error):continue
    known={r['dataset'].split('_',1)[0]for r in records}
    windows=[]
    for i,(pos,raw,ext,end)in enumerate(objects):
        if len(raw)!=195 or raw[:2]!=b'\0\0':continue
        try:name=_text(raw[2:27]);template=_text(raw[69:89])
        except UnicodeDecodeError:continue
        if not name or any(ord(c)<32 for c in name):continue
        windows.append((i,pos,name,template,raw,ext))
    graphs=[]
    for wi,(oi,pos,name,template,header,extension)in enumerate(windows):
        if name in known or template.upper()=='ORIGIN':continue
        end_index=windows[wi+1][0]if wi+1<len(windows)else len(objects)
        layer_records=[j for j in range(oi+1,end_index)if len(objects[j][1])in(361,405)and objects[j][1][:3]==b'\0\0\x1f']
        width,height=struct.unpack_from('<HH',header,35);dx,dy=struct.unpack_from('<HH',header,87)
        try:long_name=_text(extension).split('@${',1)[0]
        except UnicodeDecodeError:long_name=''
        graph={'name_hex':name.encode().hex(),'label_hex':long_name.encode().hex(),
            'title_mode_raw':header[105]&3,'template_name_hex':template.encode().hex(),
            'width_raw':width,'height_raw':height,'dpi_raw':[dx,dy],
            'is_layout':template.upper()=='LAYOUT','is3d':False,'layers':[],
            'record_offset':pos,'raw_header_hex':header.hex(),'header_extension_hex':extension.hex()}
        for li,j in enumerate(layer_records):
            _,raw,ext,_=objects[j];stop=layer_records[li+1]if li+1<len(layer_records)else end_index
            x=struct.unpack_from('<3d',raw,15);y=struct.unpack_from('<3d',raw,58)
            if not all(math.isfinite(v)for v in x+y):continue
            layer={'name':_text(ext)or str(li+1),'client_rect':list(struct.unpack_from('<4h',raw,113)),
                'x_axis':{'min':x[0],'max':x[1],'step':x[2],'scale_raw':raw[56]},
                'y_axis':{'min':y[0],'max':y[1],'step':y[2],'scale_raw':raw[99]},
                'legend_hex':'','texts':[],'curves':[],'unmapped_annotation_count':0,
                'record_offset':objects[j][0],'raw_header_hex':raw.hex()}
            annotations=None;axis_parameters=[]
            for pp,rr,ee,_ in objects[j+1:stop]:
                if len(rr)in(515,519)and rr[0]==1:
                    yi=struct.unpack_from('<H',rr,4)[0];xi=struct.unpack_from('<H',rr,35)[0]
                    # Unknown IDs remain explicit failures in the graph importer.
                    layer['curves'].append({'type_raw':rr[76],'hidden':rr[38]==33,
                        'x_dataset_id':xi,'y_dataset_id':yi,'row_range_raw':list(struct.unpack_from('<II',rr,7)),'line_connect_raw':rr[17],
                        'line_style_raw':rr[18],'line_width_raw':struct.unpack_from('<H',rr,21)[0]/500,
                        'symbol_shape_raw':rr[23],'symbol_size_raw':struct.unpack_from('<H',rr,25)[0]/500,
                        'line_color':_color(rr[362:366]),'fill_color':_color(rr[194:198]),'record_offset':pp,'raw_header_hex':rr.hex()})
                elif len(rr)in(515,519)and rr[0]==17:
                    axis_parameters.append(rr)
                elif len(rr)in(133,159):
                    try:annotations=(_text(rr[70:111]),rr)
                    except UnicodeDecodeError:annotations=None
                elif len(rr)==111 and annotations and ee:
                    aname,ah=annotations
                    try:value=_text(ee)
                    except UnicodeDecodeError:continue
                    item={'name':aname,'text_hex':value.encode().hex(),
                          'font_size_raw':struct.unpack_from('<H',rr,4)[0],
                          'rect_raw':list(struct.unpack_from('<4h',ah,3)),
                          'attach_raw':ah[40],'color':_color(ah[51:55])}
                    if aname in('XB','YL'):
                        axis=layer['x_axis'if aname=='XB'else'y_axis'];axis['title_hex']=item['text_hex'];axis['title_size_raw']=item['font_size_raw']
                    elif aname=='Legend':layer['legend_hex']=item['text_hex'];layer['legend_size_raw']=item['font_size_raw']
                    else:layer['texts'].append(item)
                    annotations=None
            if len(axis_parameters)in(12,18):
                for k,key in enumerate(('x_axis','y_axis')):
                    a=axis_parameters[k*6:(k+1)*6];axis=layer[key]
                    axis.update(tick_font_size_raw=struct.unpack_from('<H',a[2],21)[0],
                        tick_value_type_raw=a[2][37]&15,tick_dataset_id=struct.unpack_from('<H',a[2],35)[0],
                        axis_width_raw=struct.unpack_from('<H',a[3],21)[0]/500,
                        tick_direction_raw=(a[3][37]>>4)&3,
                        opposite_visible=a[5][38]!=0,grid_visible=a[1][38]!=0,visible=a[3][38]!=0)
            graph['layers'].append(layer)
        graphs.append(graph)
    return graphs
