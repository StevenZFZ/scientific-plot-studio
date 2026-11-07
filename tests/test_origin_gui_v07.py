"""GUI contract tests; all numeric inputs are synthetic."""
import copy
import json
import threading
from pathlib import Path
import pytest
from PySide6.QtWidgets import QFileDialog
from sps import origin_data
from test_office_gui import app,window,wait
from test_origin_reader import fixture as binary_fixture,DECODER


def recovery():
    return {'schema':'sps.origin-data/1','filename':'synthetic.opju','format':'opju',
            'raw':{'source_sha256':'a'*64,'counts':{'metadata':1},
                   'rejected':[{'dataset':'Unsupported_A','reason':'synthetic unsupported encoding'}]},
            'warnings':['这是合成测试；部分读取，不是完整工程恢复。'],
            'spreadsheets':[{'name':'Book1@1','columns':[
                {'name':'A','role':None,'units':None,'logical_rows':1,'data':[None,1.0000000000000002,-0.0,None]},
                {'name':'B','role':'Y','units':None,'logical_rows':1,'data':[None,3.,4.,None,None]}]}]}


def test_explicit_rows_preview_unknown_metadata_and_complete_save(window,app,tmp_path,monkeypatch):
    w,errors=window;p=w.office_panel;r=recovery();before=copy.deepcopy(r)
    p.set_recovery(r);assert p.x.currentIndex()==p.y.currentIndex()==-1
    assert '1 列未支持' in p.coverage.toPlainText() and 'Unsupported_A' in p.coverage.toPlainText()
    assert p.columns_table.item(0,1).text()=='未知 / 未映射 / 未知'
    assert p.preview_table.item(0,0).text()=='[缺失]'
    p.x.setCurrentIndex(0);p.y.setCurrentIndex(1);p.add_pair()
    assert not p.pairs and '不会自动截断' in p.status.text()
    p.use_range.setChecked(True);p.row_start.setValue(2);p.row_stop.setValue(3)
    p.add_pair();assert p.pairs==[[0,0,1]]
    w.saved_hash=w.project.fingerprint();p.reconstruct()
    assert w.project.datasets[0].columns=={'X':[1.0000000000000002,-0.0],'Y':[3.,4.]}
    assert w.project.audit[0]['mappings'][0]['row_range']==[1,3]
    assert r==before and len(r['spreadsheets'][0]['columns'][1]['data'])==5
    destination=tmp_path/'full-recovery.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(destination),'JSON'))
    p.save_recovery();assert json.loads(destination.read_text())==before
    p.row_stop.setValue(4);assert p.pairs==[]
    p.add_pair();assert p.pairs==[] and '缺失' in p.status.text()


def test_reader_edit_invalidates_background_result_and_aba_source(window,app,monkeypatch):
    w,_=window;p=w.office_panel;release=threading.Event();entered=threading.Event()
    def read(*a):entered.set();release.wait(3);return recovery()
    monkeypatch.setattr(origin_data,'read_any',read)
    p.source.setText('synthetic.opju');p.read_data();assert entered.wait(1)
    p.source.setText('temporary.opju');p.source.setText('synthetic.opju')
    p.decoder.setText('new-reviewed-path')
    release.set();wait(app,p)
    assert p.recovery is None and '未采用旧结果' in p.status.text()
    p.set_recovery(recovery());p.probe.setText('another-probe')
    assert p.recovery is None and p.sheet.count()==0 and not p.pairs


def test_main_open_opju_uses_real_backend_without_style_parser(window,app,tmp_path):
    if not DECODER.exists():pytest.skip('Optional pinned decoder not bundled')
    w,_=window;source=tmp_path/'two-columns.opju'
    a=tmp_path/'a.opju';b=tmp_path/'b.opju'
    first=binary_fixture(a,(1.0000000000000002,2.),metadata=False)
    second=binary_fixture(b,(3.,4.),metadata=False).split(b'\n',1)[1].replace(b'Book1_A',b'Book1_B')
    source.write_bytes(first+second);before=source.read_bytes()
    w.open_project(source);wait(app,w.office_panel)
    p=w.office_panel
    assert w.workspaces.currentIndex()==w.office_index and p.sections.currentIndex()==0
    assert p.recovery['format']=='opju' and p.sheet.count()==1 and p.x.count()==2
    assert '2 列恢复' in p.coverage.toPlainText()
    p.x.setCurrentIndex(0);p.y.setCurrentIndex(1);p.add_pair();assert p.pairs==[[0,0,1]]
    w.saved_hash=w.project.fingerprint();p.reconstruct()
    assert w.project.datasets[0].columns=={'X':[1.0000000000000002,2.],'Y':[3.,4.]}
    assert source.read_bytes()==before


def test_sheet_switch_keeps_explicit_mappings_and_source_change_resets_axis_labels(window,app):
    w,_=window;p=w.office_panel;r=recovery()
    for c in r['spreadsheets'][0]['columns']:c['data']=[1.,2.]
    second=copy.deepcopy(r['spreadsheets'][0]);second['name']='Book2@1';r['spreadsheets'].append(second)
    p.set_recovery(r);p.x.setCurrentIndex(0);p.y.setCurrentIndex(1);p.add_pair()
    p.sheet.setCurrentIndex(1);p.x.setCurrentIndex(0);p.y.setCurrentIndex(1);p.add_pair()
    assert p.pairs==[[0,0,1],[1,0,1]]
    p.xlabel.setText('Old unit');p.source.setText('new-source.opju')
    assert p.xlabel.text()=='X' and p.ylabel.text()=='Y' and not p.pairs
