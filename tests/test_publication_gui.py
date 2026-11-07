import copy
from PySide6.QtWidgets import QDialog
from test_gui import app,window
from test_office_gui import wait
from test_origin_graphs import decoder,binary_project
from sps.publication_ui import AxesDialog,PublicationDialog
from sps.commands import Session
from sps.publication import framed_sides


def wait_preview(app,d):
    from PySide6.QtTest import QTest
    import time
    end=time.monotonic()+20
    while d.task and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert d.task is None,d.report.toPlainText()


def test_axis_grid_edits_frames_ticks_and_labels_separately(window,app,monkeypatch):
    w,_=window
    def choose(d):
        d.set_framed();assert d.fields['top']['spine'].isChecked()
        assert not d.fields['top']['ticks'].isChecked()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(AxesDialog,'exec',choose)
    w.edit_axis_sides();assert w.project.figure.axis_sides==framed_sides()
    w.undo();assert w.project.figure.axis_sides is None


def test_journal_preview_approval_invalidates_when_font_or_target_changes(window,app):
    w,_=window;before=w.project.fingerprint()
    d=PublicationDialog(w.session,{'font':'DejaVu Sans'},w);d.show();d.preview();wait_preview(app,d)
    assert d.plan and d.apply.isEnabled()and not d.image._source.isNull()
    assert w.project.fingerprint()==before
    sealed=d.plan;d.invalidate();assert d.plan==sealed and d.apply.isEnabled()
    d.profile.setCurrentIndex(1);assert d.plan is None and not d.apply.isEnabled()
    d.font.setCurrentText('SPS missing font 123');d.preview()
    assert not d.plan and '未安装'in d.report.toPlainText()
    d.reject()


def test_journal_dialog_apply_whole_review_and_save_preference(window,app,tmp_path,monkeypatch):
    w,_=window;w.publication_settings=tmp_path/'prefs.json'
    d=PublicationDialog(w.session,{'font':'DejaVu Sans'},w);d.auto.setChecked(True)
    d.preview();wait_preview(app,d);assert d.plan
    monkeypatch.setattr('sps.gui.PublicationDialog',lambda *args:d)
    monkeypatch.setattr(d,'exec',lambda:QDialog.DialogCode.Accepted)
    data=copy.deepcopy(w.project.datasets);w.publication_dialog()
    assert w.project.figure.font_size==7 and w.project.datasets==data
    assert w.publication_settings.is_file()and w.publication_preferences['enabled']
    w.undo();assert w.project.figure.layout_mode=='source'


def test_origin_auto_normalization_only_after_explicit_preference(window,app,tmp_path,decoder):
    w,_=window;w.publication_settings=tmp_path/'prefs.json';w.publication_preferences={'enabled':True,'profile':'nature','size':'single','font':'DejaVu Sans','scope':'all'}
    source=tmp_path/'example.opju';before=binary_project(source)
    w.open_project(source);wait(app,w.office_panel)
    assert [p.name for p in w.project.pages]==['Graph10','豆腐图']
    assert all(p.layers[0].figure.font_size==7 for p in w.project.pages)
    assert source.read_bytes()==before
    assert any(a.get('actor')=='publication_auto_import'for a in w.project.audit)
