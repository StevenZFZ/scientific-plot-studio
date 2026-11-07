import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import pytest
from PySide6.QtWidgets import QApplication,QMessageBox
from sps.gui import MainWindow
from sps.model import demo
from sps import transfer,origin_data
from test_office import recovery_fixture,ppt_fixture

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def window(app,tmp_path,monkeypatch):
    errors=[];monkeypatch.setattr(QMessageBox,'warning',lambda *a:errors.append(str(a[-1])))
    w=MainWindow(demo(),library_dir=tmp_path/'library');w.show();app.processEvents()
    yield w,errors
    # Qt offscreen's platform clipboard must be released before QApplication
    # destruction; real Cocoa shutdown is separately tested without this cleanup.
    QApplication.clipboard().clear();app.processEvents()
    w.saved_hash=w.project.fingerprint();w.close();assert not errors


def wait(app,panel):
    deadline=time.monotonic()+10
    while panel.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents();assert not panel.busy


def test_clipboard_native_data_and_image_fallback(window,app):
    w,errors=window;before=w.project.fingerprint();w.copy_editable();app.processEvents()
    mime=QApplication.clipboard().mimeData();assert mime.hasFormat(transfer.MIME) and mime.hasImage()
    assert transfer.decode(bytes(mime.data(transfer.MIME))).fingerprint()==before
    w.project.figure.title='different';w.saved_hash=w.project.fingerprint()
    w.paste_editable();assert w.project.fingerprint()==before


def test_ppt_import_extraction_and_explicit_mapping(window,app,tmp_path):
    w,errors=window;panel=w.office_panel;source=tmp_path/'origin.pptx';ppt_fixture(source,b'CPYUA 4.3\n')
    panel.scan(source);wait(app,panel);assert panel.report['counts']['opju']==1
    panel.extract_to(tmp_path/'recovered');wait(app,panel);panel.select_object(0)
    assert panel.source.text().endswith('.opju') and '不能读取' in panel.status.text()
    panel.set_recovery(recovery_fixture());assert panel.x.currentIndex()==panel.y.currentIndex()==-1
    panel.x.setCurrentIndex(0);panel.y.setCurrentIndex(1);panel.add_pair()
    assert panel.pairs==[[0,0,1]]
    w.saved_hash=w.project.fingerprint();panel.reconstruct()
    assert w.project.datasets[0].columns['X']==[1.,1.0000000000000002]
    assert w.workspaces.currentIndex()==0
    panel.source.setText('/another/source.opj')
    assert panel.recovery is None and not panel.pairs and panel.sheet.count()==0


def test_editable_pptx_gui_export_and_recovery(window,app,tmp_path):
    w,errors=window;w.project.figure.annotations=[];before=w.project.fingerprint()
    target=tmp_path/'figure.pptx';assert w.export_pptx(target)['series']==2
    w.project.figure.title='changed';w.saved_hash=w.project.fingerprint()
    w.open_project(target);app.processEvents();assert w.project.fingerprint()==before
