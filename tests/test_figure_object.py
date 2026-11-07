import copy,io,json,struct,subprocess,sys,zipfile,zlib
from pathlib import Path
import pytest
from PIL import Image
from sps import figure_object as obj,figure_links as links,office_figures as office
from sps.model import demo,Project,GraphPage,GraphLayer,save


@pytest.fixture(scope='module')
def portable():return obj.build(demo())


def test_selected_view_and_complete_shared_document_survive():
    original=demo();one=copy.deepcopy(original.figure);two=copy.deepcopy(one)
    for s in two.series:s.id+='second'
    p=Project(datasets=original.datasets,pages=[GraphPage('p1','First',[GraphLayer('l1','Main',one)]),GraphPage('p2','豆腐图',[GraphLayer('l2','Main',two)])])
    p.select_context(1);result=obj.unpack(obj.build(p))
    assert result['project'].context==(1,0)and len(result['project'].pages)==2
    assert result['project'].to_dict()==p.to_dict()
    assert result['manifest']['context']=={'page':1,'layer':0}


def test_changed_pixels_reject_old_embedded_data(portable):
    raw=obj.unpack(portable)['files']['preview.png'];im=Image.open(io.BytesIO(raw)).convert('RGBA');im.putpixel((0,0),(255,0,0,255));out=io.BytesIO();im.save(out,format='PNG');png=out.getvalue()
    block=struct.pack('>I',len(portable))+obj.PNG_TAG+portable+struct.pack('>I',zlib.crc32(obj.PNG_TAG+portable)&0xffffffff)
    changed=png[:-12]+block+png[-12:]
    with pytest.raises(ValueError,match='改变'):obj.from_png(changed)


def test_svg_external_changes_are_not_latest_data(portable):
    svg=obj.svg_carrier(portable)
    with pytest.raises(ValueError,match='改变'):obj.from_svg(svg.replace(b'<svg ',b'<svg data-external-edit="true" ',1))
    with pytest.raises(ValueError):obj.from_png(obj.unpack(portable)['files']['preview.png'])


def test_uuid_only_links_no_commands_or_external_fetch(tmp_path):
    published=links.publish(demo(),tmp_path/'links');url=published['url'];assert links.resolve(url,tmp_path/'links')==published['path'].resolve()
    for value in('https://example.com','spsfigure://edit/../../etc/passwd','spsfigure://edit/'+obj.unpack(published['path'].read_bytes())['manifest']['id']+'?command=run','spsfigure://evil/id'):
        with pytest.raises(ValueError):links.resolve(value,tmp_path/'links')
    assert links.restore(published['path'].read_bytes(),tmp_path/'links')==published['path'].resolve()


def test_copy_of_same_object_cannot_take_over_existing_editor_link(tmp_path):
    root=tmp_path/'links';published=links.publish(demo(),root)
    duplicate=tmp_path/'duplicate.spsfig';duplicate.write_bytes(published['path'].read_bytes())
    with pytest.raises(ValueError,match='本地源'):links.register(duplicate,root)
    assert links.resolve(published['url'],root)==published['path'].resolve()


@pytest.mark.parametrize('kind',['docx','pptx'])
def test_office_full_data_roundtrip_and_refresh_clone_preserves_layout(tmp_path,kind):
    original=demo();root=tmp_path/'links';source=tmp_path/('original.'+kind)
    created=office.export(original,source,root);before=source.read_bytes();recovered=office.recover(source)
    assert recovered[0]['info']['project'].to_dict()==original.to_dict()
    path=Path(created['figure']);old=obj.load(path);edited=old['project'];edited.figure.series[0].color='#aa2244'
    obj.save(edited,path,expected_sha=old['sha256']);links.register(path,root)
    target=tmp_path/('new.'+kind);report=office.refresh(source,target,root)
    assert report['updated'][0]['revision']==2 and source.read_bytes()==before
    assert office.recover(target)[0]['info']['project'].to_dict()==edited.to_dict()
    with zipfile.ZipFile(source)as a,zipfile.ZipFile(target)as b:
        main=recovered[0]['record']['main'];assert a.read(main)==b.read(main)
    with pytest.raises(ValueError):office.refresh(source,source,root)
    with pytest.raises(ValueError):office.refresh(source,target,root)


def test_old_office_restore_does_not_overwrite_newer_local_revision(tmp_path):
    created=office.export(demo(),tmp_path/'first.pptx',tmp_path/'links');old=office.recover(tmp_path/'first.pptx')[0]['package']
    path=Path(created['figure']);info=obj.load(path);p=info['project'];p.figure.title='new local edit';obj.save(p,path,expected_sha=info['sha256']);before=path.read_bytes()
    with pytest.raises(ValueError,match='旧版本'):links.restore(old,tmp_path/'links')
    assert path.read_bytes()==before


@pytest.mark.parametrize('kind',['docx','pptx'])
def test_office_renamed_media_and_relationship_ids_resolve_by_drawing(tmp_path,kind):
    source=tmp_path/('original.'+kind);root=tmp_path/'links';created=office.export(demo(),source,root)
    with zipfile.ZipFile(source)as z:parts={n:z.read(n)for n in z.namelist()}
    rec=office.recover(source)[0]['record'];old=rec['image'];new=old.rsplit('/',1)[0]+'/office-renamed.png'
    parts[new]=parts.pop(old)
    rel=rec['main'].rsplit('/',1)[0]+'/_rels/'+rec['main'].rsplit('/',1)[1]+'.rels'
    parts[rel]=parts[rel].replace(old.rsplit('/',1)[1].encode(),b'office-renamed.png')
    rewritten=tmp_path/('office-saved.'+kind)
    with zipfile.ZipFile(rewritten,'w')as z:
        for n,b in parts.items():z.writestr(n,b)
    assert office.recover(rewritten)[0]['record']['image']==new
    live=Path(created['figure']);info=obj.load(live);p=info['project'];p.figure.title='after host save'
    obj.save(p,live,expected_sha=info['sha256']);links.register(live,root)
    target=tmp_path/('updated.'+kind);office.refresh(rewritten,target,root)
    assert office.recover(target)[0]['info']['project'].figure.title=='after host save'
    with zipfile.ZipFile(target)as z:assert z.read(rec['main'])==parts[rec['main']]


def test_cli_export_import_and_exclusive_destination(tmp_path):
    source=tmp_path/'source.sps.json';save(demo(),source);target=tmp_path/'figure.spsfig'
    cmd=[sys.executable,'-m','sps','figure-export',str(source),str(target)]
    assert subprocess.run(cmd,capture_output=True,timeout=15).returncode==0
    assert subprocess.run(cmd,capture_output=True,timeout=15).returncode==2
    output=tmp_path/'restored.sps.json'
    assert subprocess.run([sys.executable,'-m','sps','figure-recover',str(target),str(output)],capture_output=True,timeout=15).returncode==0
    assert json.loads(output.read_text())==json.loads(source.read_text())
