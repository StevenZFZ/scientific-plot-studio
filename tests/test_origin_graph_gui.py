import copy
import threading
from PySide6.QtWidgets import QApplication
from test_gui import app,window
from test_office_gui import wait
from test_origin_graphs import binary_project,decoder
from sps import origin_graphs
from sps.model import load


def test_open_origin_auto_reads_all_tabs_and_preserves_order(window,app,tmp_path,decoder):
    w,_=window;source=tmp_path/'source.opju';before=binary_project(source)
    w.open_project(source);wait(app,w.office_panel)
    assert w.workspaces.currentIndex()==w.editor_index
    assert [w.graph_tabs.tabText(i)for i in range(w.graph_tabs.count())]==['Graph10','豆腐图']
    fingerprint=w.project.fingerprint()
    w.graph_tabs.setCurrentIndex(1);app.processEvents()
    assert w.project.context==(1,0)and w.project.fingerprint()==fingerprint
    assert w.layer_combo.count()==1 and w.canvas.figure.axes
    assert w.data_table.columnWidth(0)>=150
    assert '(Y)' in w.data_table.horizontalHeaderItem(0).text()
    assert w.project_path is None and source.read_bytes()==before
    target=tmp_path/'all.sps.json';w.save_project(path=target)
    assert len(load(target).pages)==2


def test_reader_does_not_replace_edits_made_while_loading(window,app,tmp_path,decoder,monkeypatch):
    w,_=window;source=tmp_path/'source.opju';binary_project(source)
    result=origin_graphs.read_project(source,decoder=decoder)
    entered=threading.Event();release=threading.Event()
    def read(*args):entered.set();release.wait(4);return result
    monkeypatch.setattr(origin_graphs,'read_project',read)
    w.open_project(source)
    try:
        assert entered.wait(1)
        w.execute([{'op':'set_figure','changes':{'title':'Concurrent edit'}}])
    finally:release.set();wait(app,w.office_panel)
    assert w.project.figure.title=='Concurrent edit' and not w.project.pages
    assert '未覆盖'in w.import_summary.text()


def test_page_switch_invalidates_previous_export_cache(window,app,tmp_path,decoder):
    w,_=window;source=tmp_path/'source.opju';binary_project(source,names=('A','B'))
    w.open_project(source);wait(app,w.office_panel)
    basis=w.export_basis();w._export_basis=basis;w.last_export={'synthetic':True}
    w.graph_tabs.setCurrentIndex(1);app.processEvents()
    assert w.export_basis()!=basis and w.last_export is None
    assert w.export_preview.original.isNull()


def test_layer_switch_and_edit_undo_retains_other_pages(window,app,tmp_path,decoder):
    w,_=window;source=tmp_path/'source.opju';binary_project(source,names=('A','B'))
    p=origin_graphs.read_project(source,decoder=decoder)['project']
    layer=copy.deepcopy(p.pages[0].layers[0]);layer.id='second_layer'
    layer.figure.series[0].id='second_series';layer.name='Inset';layer.rect=[.6,.6,.2,.2]
    p.pages[0].layers.append(layer)
    w.replace_project(p,check_layout=False);other=copy.deepcopy(w.project.pages[1])
    w.layer_combo.setCurrentIndex(1);app.processEvents()
    assert w.project.context==(0,1)
    w.execute([{'op':'set_series','ids':['second_series'],'changes':{'color':'#ff0000'}}])
    assert w.project.pages[1]==other
    w.graph_tabs.setCurrentIndex(1);w.undo()
    assert w.project.context==(0,1)and w.graph_tabs.currentIndex()==0
    assert w.project.figure.series[0].color=='#2c4258'


def test_failed_page_does_not_leave_previous_scientific_picture(window,app):
    from sps.model import GraphPage,GraphLayer,Project,FigureSpec
    w,_=window
    w.replace_project(Project(pages=[GraphPage('a','A',[GraphLayer('la','1',FigureSpec())]),GraphPage('b','B',[GraphLayer('lb','1',FigureSpec(font='SPS Nonexistent Font 123456'))])]),check_layout=False)
    assert w.canvas.figure.axes
    w.graph_tabs.setCurrentIndex(1);app.processEvents()
    assert w.render_error and not w.canvas.figure.axes
    assert '当前图预览未完成' in w.import_summary.text()
