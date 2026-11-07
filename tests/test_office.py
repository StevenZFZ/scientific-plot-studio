import copy
import io
import json
import math
from pathlib import Path
import struct
import zipfile
import xml.etree.ElementTree as ET
import pytest
from sps import office, origin_data, pptx_io, transfer
from sps.model import demo


def compound(payload):
    """Small synthetic CFB with one regular Contents stream, no private sample."""
    header=bytearray(512);header[:8]=office.CFB
    struct.pack_into('<HHHH',header,24,0x3e,3,0xfffe,9);struct.pack_into('<H',header,32,6)
    struct.pack_into('<IIIIIIIII',header,40,0,1,1,0,4096,0xfffffffe,0,0xfffffffe,0)
    struct.pack_into('<109I',header,76,0,*([0xffffffff]*108))
    fat=[0xffffffff]*128;fat[0]=0xfffffffd;fat[1]=0xfffffffe
    for i in range(2,10):fat[i]=i+1 if i<9 else 0xfffffffe
    directory=bytearray(512)
    for i,(name,kind,start,size,child) in enumerate([('Root Entry',5,0xfffffffe,0,1),('Contents',2,2,4096,0xffffffff)]):
        offset=i*128;name=(name+'\0').encode('utf-16le');directory[offset:offset+len(name)]=name
        struct.pack_into('<HBBIII',directory,offset+64,len(name),kind,1,0xffffffff,0xffffffff,child)
        struct.pack_into('<IQ',directory,offset+116,start,size)
    return bytes(header)+struct.pack('<128I',*fat)+bytes(directory)+payload.ljust(4096,b'\0')


def ppt_fixture(path, payload, linked=False):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{office.P}" xmlns:r="{office.REL}"><p:sldIdLst><p:sldId r:id="slide"/></p:sldIdLst></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels',f'<Relationships xmlns="{office.R}"><Relationship Id="slide" Target="slides/slide12.xml"/></Relationships>')
        z.writestr('ppt/slides/slide12.xml',f'<p:sld xmlns:p="{office.P}" xmlns:r="{office.REL}"><p:oleObj r:id="obj" spid="8" progId="Origin95.Graph"/></p:sld>')
        z.writestr('ppt/slides/_rels/slide12.xml.rels',f'<Relationships xmlns="{office.R}"><Relationship Id="obj" Target="'+('https://example.invalid/project.opj" TargetMode="External' if linked else '../embeddings/oleObject1.bin')+'"/></Relationships>')
        if not linked:z.writestr('ppt/embeddings/oleObject1.bin',compound(payload))


@pytest.mark.parametrize('magic,fmt',[(b'CPYA 4.1 #\n','opj'),(b'CPYUA 4.3\n','opju')])
def test_extract_exact_origin_and_ole_without_activation(tmp_path,magic,fmt):
    path=tmp_path/'test.pptx';ppt_fixture(path,magic+b'fixture-data');before=path.read_bytes()
    report=office.scan(path);item=report['objects'][0]
    assert item['format']==fmt and item['uses'][0]['slide']==1 and item['uses'][0]['slide_part'].endswith('slide12.xml')
    destination=tmp_path/'recovered';result=office.extract(path,destination);obj=result['objects'][0]
    assert (destination/obj['file']).read_bytes()==(magic+b'fixture-data').ljust(4096,b'\0')
    assert office.sha((destination/obj['file']).read_bytes())==obj['sha256']
    assert (destination/obj['ole_file']).read_bytes()==compound(magic+b'fixture-data')
    assert path.read_bytes()==before and result['source']['unchanged']
    with pytest.raises(ValueError,match='已存在'):office.extract(path,destination)


def test_external_links_and_images_are_not_data(tmp_path):
    path=tmp_path/'linked.pptx';ppt_fixture(path,b'CPYA ',linked=True)
    report=office.scan(path);assert report['counts']['external_links']==1 and not report['objects']
    image=tmp_path/'image.pptx';ppt_fixture(image,b'PNG-data')
    report=office.scan(image);assert not report['objects'] and len(report['ignored'])==1


def test_office_rejects_paths_duplicate_parts_and_entities(tmp_path):
    path=tmp_path/'bad.pptx'
    with zipfile.ZipFile(path,'w') as z:z.writestr('../file','bad')
    with pytest.raises(ValueError,match='路径'):office.scan(path)
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('same','one')
        with pytest.warns(UserWarning):z.writestr('same','two')
    with pytest.raises(ValueError,match='重复'):office.scan(path)
    for encoding in ['utf-8','utf-16']:
        data='<?xml version="1.0" encoding="'+encoding+'"?><!DOCTYPE x [<!ENTITY a "data">]><x>&a;</x>'
        with pytest.raises(ValueError):office.xml(data.encode(encoding))


def recovery_fixture():
    col=lambda name,values,role:{'name_hex':name.encode().hex(),'data':values,'sheet_raw':0,'type_raw':role}
    return {'source':{'name':'fixture.opj','sha256':'a'*64},'probe':{'schema':'sps.experimental.origin-probe/1','spreads':[{'name_hex':'426f6f6b31','columns':[col('C',[1.,1.0000000000000002],0),col('D',[3.,4.],1)]}]}}


def test_explicit_reconstruction_exact_and_non_destructive():
    with pytest.raises(ValueError,match='请先读取'):origin_data.reconstruct(None,[[0,0,1]])
    r=recovery_fixture();before=copy.deepcopy(r)
    p=origin_data.reconstruct(r,[[0,0,1]],'Strain (%)','Stress (MPa)')
    assert r==before and p.datasets[0].columns['X']==[1.,1.0000000000000002]
    assert p.figure.xlabel=='Strain (%)' and p.audit[0]['mappings'][0]['rows_removed']==0
    for values in [[1.,None],[1.,'2'],[math.nan,3.],[1.]]:
        bad=recovery_fixture();bad['probe']['spreads'][0]['columns'][0]['data']=values
        with pytest.raises(ValueError):origin_data.reconstruct(bad,[[0,0,1]])
    for pairs in [[],[[0,0,0]],[[3,0,1]],[[0,-1,1]],[[0,None,1]]]:
        with pytest.raises(ValueError):origin_data.reconstruct(r,pairs)


def test_opju_rejected_before_reader(tmp_path):
    source=tmp_path/'file.opju';source.write_bytes(b'CPYUA 4.3748 212\nfixture')
    with pytest.raises(ValueError,match='尚未实现'):origin_data.read(source,Path(__file__))


def test_empty_reader_success_is_rejected(tmp_path):
    import sys
    source=tmp_path/'sample.opj';source.write_bytes(b'CPYA 4.3 #\nfixture')
    probe=tmp_path/'probe'
    probe.write_text(f'#!{sys.executable}\nimport sys,json\nopen(sys.argv[2],"w").write(json.dumps({{"schema":"sps.experimental.origin-probe/1","spreads":[],"excels":[]}}))\n')
    probe.chmod(0o700)
    with pytest.raises(ValueError,match='任何工作表'):origin_data.read(source,probe)


def test_full_clipboard_roundtrip_and_hash_rejection():
    p=demo();q=transfer.decode(transfer.encode(p));assert p.to_dict()==q.to_dict()
    data=json.loads(transfer.encode(p));data['project']['datasets'][0]['columns']['Reference'][0]+=1
    with pytest.raises(ValueError,match='摘要'):transfer.decode(json.dumps(data).encode())
    with pytest.raises(ValueError):transfer.decode(b'{}')


def lines():
    p=demo();p.figure.annotations=[];return p


def test_pptx_has_native_chart_and_workbook_exact_sps_recovery(tmp_path):
    p=lines();before=p.fingerprint();target=tmp_path/'editable.pptx'
    report=pptx_io.export(p,target)
    assert p.fingerprint()==before and report['series']==2
    assert pptx_io.recover(target).to_dict()==p.to_dict()
    with zipfile.ZipFile(target) as z:
        chart=ET.fromstring(z.read('ppt/charts/chart1.xml'));ns={'c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
        assert chart.find('.//c:scatterChart',ns) is not None
        assert len(chart.findall('.//c:ser',ns))==2
        wb=z.read('ppt/embeddings/Microsoft_Excel_Sheet1.xlsx')
        with zipfile.ZipFile(io.BytesIO(wb)) as x:
            sheet=x.read('xl/worksheets/sheet1.xml')
            assert b'<sheetData>' in sheet
    with pytest.raises(ValueError,match='已存在'):pptx_io.export(p,target)


def test_reject_stale_ppt_data_and_unsupported_chart_without_output(tmp_path):
    p=lines();target=tmp_path/'editable.pptx';pptx_io.export(p,target)
    with zipfile.ZipFile(target) as z:parts={n:z.read(n) for n in z.namelist()}
    parts['ppt/charts/chart1.xml']+=b'\n'
    stale=tmp_path/'stale.pptx'
    with zipfile.ZipFile(stale,'w') as z:
        for name,blob in parts.items():z.writestr(name,blob)
    with pytest.raises(ValueError,match='已变化'):pptx_io.recover(stale)
    p.figure.series[0].kind='scatter'
    rejected=tmp_path/'unsupported.pptx'
    with pytest.raises(ValueError,match='纯折线'):pptx_io.export(p,rejected)
    assert not rejected.exists()


def test_scientific_labels_are_literal_workbook_strings(tmp_path):
    p=lines();p.figure.series[0].label='=1+1';p.figure.series[1].label='https://example.invalid/data'
    target=tmp_path/'literal.pptx';pptx_io.export(p,target)
    with zipfile.ZipFile(target) as z:
        with zipfile.ZipFile(io.BytesIO(z.read('ppt/embeddings/Microsoft_Excel_Sheet1.xlsx'))) as wb:
            root=ET.fromstring(wb.read('xl/worksheets/sheet1.xml'))
            assert root.find('.//{*}f') is None and root.find('.//{*}hyperlinks') is None
    assert pptx_io.recover(target).figure.series[0].label=='=1+1'
