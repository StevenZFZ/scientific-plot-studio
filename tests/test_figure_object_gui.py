import pytest
from pathlib import Path
from test_gui import app,window
from sps import figure_object as obj,figure_links as links,office_figures as office
from sps.model import demo,load


@pytest.fixture(autouse=True)
def clear_local_test_clipboard(app):
    yield
    app.clipboard().clear()


def test_object_open_edit_save_revision_and_native_save_as(window,app,tmp_path):
    w,_=window;w.figure_links_root=tmp_path/'links';path=tmp_path/'figure.spsfig';original=obj.save(demo(),path)
    w.open_project(path);assert w.figure_path==path and w.figure_sha==original['sha256']
    w.execute([{'op':'set_figure','changes':{'title':'Edited portable'}}]);assert w.save_project()
    assert obj.load(path)['manifest']['revision']==2
    assert obj.load(path)['project'].figure.title=='Edited portable'
    native=tmp_path/'native.sps.json';assert w.save_project(save_as=True,path=native)
    assert w.figure_path is None
    before=path.read_bytes();w.execute([{'op':'set_figure','changes':{'title':'Native only'}}]);assert w.save_project()
    assert path.read_bytes()==before and load(native).figure.title=='Native only'


def test_office_link_mime_context_and_png_open(window,app,tmp_path):
    w,_=window;w.figure_links_root=tmp_path/'links';before=w.project.to_dict();item=w.copy_office_figure();assert item
    mime=app.clipboard().mimeData();assert mime.hasFormat('text/rtf')and mime.hasImage()and mime.hasFormat(obj.MIME)
    assert not mime.hasHtml()and item['url'].encode()in bytes(mime.data('text/rtf'))
    assert obj.unpack(bytes(mime.data(obj.MIME)))['project'].to_dict()==before
    png=tmp_path/'portable.png';png.write_bytes(item['png']);w.open_project(png)
    assert w.project.to_dict()==before and w.figure_path
    w.open_project(item['url']);assert w.project.to_dict()==before


def test_docx_export_recover_and_new_copy_update(window,app,tmp_path):
    w,_=window;w.figure_links_root=tmp_path/'links';path=tmp_path/'figure.docx';created=w.export_office_figure(path);assert created
    w.open_project(created['figure']);w.execute([{'op':'set_figure','changes':{'title':'Office update'}}]);assert w.save_project()
    target=tmp_path/'updated.docx';assert w.refresh_office_figure(path,target)
    w.open_project(target);assert w.project.figure.title=='Office update'
    assert office.recover(path)[0]['info']['project'].figure.title!=w.project.figure.title


def test_externally_changed_object_rejects_overwrite(window,app,tmp_path):
    w,errors=window;w.figure_links_root=tmp_path/'links';path=tmp_path/'object.spsfig';obj.save(demo(),path);w.open_project(path)
    external=obj.load(path);p=external['project'];p.figure.title='external';obj.save(p,path,expected_sha=external['sha256']);before=path.read_bytes()
    w.execute([{'op':'set_figure','changes':{'title':'local'}}]);assert not w.save_project()
    assert '其他程序修改'in errors.pop()and path.read_bytes()==before
