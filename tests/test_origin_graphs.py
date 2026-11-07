"""Synthetic binary records; no private source samples bundled."""
import copy
import json
import struct
import subprocess
import sys
import pytest
from sps.origin_graphs import read_project,reconstruct_graphs
from sps.origin_reader import OriginProject
from sps.opju_strings import lz4_block,resolve_pool
from sps.model import load,save
from sps.render import draw,export_bundle
from sps.commands import Session
from sps import ai
from test_origin_reader import fixture,record,uint,DECODER


def binary_project(path,names=('Graph10','豆腐图'),bad_reference=False):
    a=path.with_name('a.opju');b=path.with_name('b.opju')
    data=fixture(a,(1.0000000000000002,None,-0.0),metadata=False)
    data+=fixture(b,(10.,20.),metadata=False).split(b'\n',1)[1].replace(b'Book1_A',b'Book1_B')
    for name in names:
        window=bytearray(195);encoded=name.encode();window[2:2+len(encoded)]=encoded
        window[69:73]=b'LINE';window[105]=2
        struct.pack_into('<HH',window,35,1200,800);struct.pack_into('<HH',window,87,254,254)
        layer=bytearray(405);layer[2]=31
        struct.pack_into('<3d',layer,15,0.,30.,10.);struct.pack_into('<3d',layer,58,-1.,4.,1.)
        struct.pack_into('<4h',layer,113,220,100,1080,640)
        curve=bytearray(519);curve[0]=1;curve[17]=1;curve[18]=2;curve[76]=200
        struct.pack_into('<H',curve,4,1);struct.pack_into('<H',curve,35,999 if bad_reference else 2)
        struct.pack_into('<II',curve,7,0,2);struct.pack_into('<H',curve,21,1250)
        curve[362:366]=bytes((44,66,88,1))
        data+=record(window)+record(layer,b'Layer1')+record(curve)
    path.write_bytes(data);return data


@pytest.fixture
def decoder():
    if not DECODER.is_file():pytest.skip('Pinned optional decoder not bundled')
    return DECODER


def test_binary_graph_order_names_reversed_xy_style_and_row_window(tmp_path,decoder):
    source=tmp_path/'source.opju';before=binary_project(source)
    result=read_project(source,decoder=decoder);assert result['error']is None
    p=result['project'];assert [g.name for g in p.pages]==['Graph10','豆腐图']
    s=p.figure.series[0]
    assert s.x=='Book1@1!B' and s.y=='Book1@1!A'
    assert s.width==2.5 and s.line_style==':' and s.color=='#2c4258' and s.row_range==[0,2]
    d=p.datasets[0];assert d.columns[s.x]==[10.,20.,None]
    assert struct.pack('<d',d.columns[s.y][-1])==struct.pack('<d',-0.)
    assert d.columns[s.y][0]==1.0000000000000002
    fig,ax,*_=draw(p);assert list(ax.lines[0].get_xdata())==[10.,20.]
    assert source.read_bytes()==before
    path=tmp_path/'saved.sps.json';save(p,path);assert load(path).to_dict()==p.to_dict()


def test_unknown_reference_keeps_graph_labels_without_guessing(tmp_path,decoder):
    source=tmp_path/'unknown.opju';binary_project(source,bad_reference=True)
    p=read_project(source,decoder=decoder)['project']
    assert len(p.pages)==2 and all(not g.layers[0].figure.series for g in p.pages)
    assert all(b['status']=='unresolved'for b in p.origin['bindings'])
    assert all('没有猜配'in b['reason']for b in p.origin['bindings'])


def test_cli_import_saves_complete_document_and_protects_existing(tmp_path,decoder):
    source=tmp_path/'source.opju';binary_project(source)
    target=tmp_path/'document.sps.json'
    command=[sys.executable,'-m','sps','origin-import',str(source),str(target),'--decoder',str(decoder)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert len(load(target).pages)==2
    assert subprocess.run(command,capture_output=True,timeout=15).returncode==2


def test_lz4_literal_overlap_and_corruption_bounds():
    assert lz4_block(b'\x50hello',5)==b'hello'
    assert lz4_block(b'\x40abcd\x04\0\x50efghi',13)==b'abcdabcdefghi'
    for value,size in ((b'\x50hi',5),(b'\x10a\0\0',5),(b'\x10a\x02\0',5),(b'\xff',10)):
        with pytest.raises(ValueError):lz4_block(value,size)
    with pytest.raises(ValueError):lz4_block(b'',4_000_001)


def test_pool_reference_offsets_are_text_not_numbers():
    pool=('RT\0'+'40℃\0').encode();raw=b'\x77\x11\x11\x11\x02\0\x01\0'+struct.pack('<IIII',4,1,len(pool),2)+pool+b'\0'*4
    n=len(raw);compressed=bytes([0xf0,n-15])+raw
    marker=b'_MSER_STRINGS_PSET';data=marker+b'\x05\x01'+struct.pack('<HI',len(compressed)+4,len(raw))+compressed
    item={'array_end':0,'values':[1,4,1.25],'blocks':[{'kind':1,'rows':2},{'kind':0,'rows':1}]}
    result=resolve_pool(data,item,len(data))
    assert result['values']==['RT','40℃',1.25] and item['values']==[1,4,1.25]
    item['values'][0]=2
    with pytest.raises(ValueError,match='reference'):resolve_pool(data,item,len(data))


def test_shared_labels_errorbars_target_scoping_and_exports(tmp_path,decoder):
    source=tmp_path/'source.opju';binary_project(source,names=('A','B'))
    recovery=read_project(source,decoder=decoder)['recovery'];raw=recovery['raw']
    # Explicit source Y-parent reference: errorbar X points to the main Y ID.
    error=copy.deepcopy(raw['graphs'][0]['layers'][0]['curves'][0])
    error.update(type_raw=231,x_dataset_id=1,y_dataset_id=2)
    raw['graphs'][0]['layers'][0]['curves'].append(error)
    p=reconstruct_graphs(recovery);assert p.figure.series[0].y_error=='Book1@1!B'
    output=export_bundle(p,tmp_path/'exports','page-a',['png','svg','pdf','tiff'],100,True)
    assert output['target']['page_name']=='A' and len(output['files'])==4
    config=ai.AIConfig(model='synthetic');request=ai.prepare(p,'Unify width',config)
    before=p.fingerprint();p.select_context(1);assert p.fingerprint()==before
    with pytest.raises(ValueError):ai.validate_prepared(p,request,config)
    session=Session(p);session.execute([{'op':'set_figure','changes':{'width_mm':130}}])
    assert session.project.pages[0].layers[0].figure.width_mm==p.pages[0].layers[0].figure.width_mm
    assert session.project.figure.width_mm==130


def test_axis_labels_follow_explicit_source_and_shared_edits(tmp_path,decoder):
    source=tmp_path/'source.opju';binary_project(source,names=('Category',))
    recovery=read_project(source,decoder=decoder)['recovery'];raw=recovery['raw']
    x=copy.deepcopy(raw['datasets'][0]);x.update(dataset_id=3,column_identifier='Categories',values=['A','B','C'])
    labels=copy.deepcopy(x);labels.update(dataset_id=4,column_identifier='AxisLabels',values=['RT','Warm','Hot'])
    raw['resolved_columns']=[x,labels]
    layer=raw['graphs'][0]['layers'][0];layer['curves'][0].update(x_dataset_id=3,y_dataset_id=1,row_range_raw=[1,3])
    layer['x_axis'].update(tick_value_type_raw=1,tick_dataset_id=4,min=0,max=4)
    p=reconstruct_graphs(recovery)
    assert p.figure.xtick_column=='Book1@1!AxisLabels'
    _,ax,*_=draw(p)
    assert list(ax.lines[0].get_xdata())==[2,3]
    assert [t.get_text()for t in ax.get_xticklabels()]==['RT','Warm','Hot']
    session=Session(p)
    session.execute([{'op':'set_cell','dataset':p.datasets[0].id,'column':'Book1@1!AxisLabels','row':1,'value':'Edited'}])
    _,ax,*_=draw(session.project)
    assert [t.get_text()for t in ax.get_xticklabels()]==['RT','Edited','Hot']
    assert session.project.datasets[0].columns['Book1@1!Categories']==['A','B','C']
