import copy
import pytest
from sps.model import demo,from_dict,save,load
from sps.commands import Session,style_from_project,run_operations
from sps.render import draw
from sps import templates,pptx_io
from test_office_gui import app,window

OPTIONS={'legend_location':'upper left','legend_frame':True,'x_major_step':100.,'y_major_step':.25,'minor_divisions':2}


def test_old_json_defaults_style_template_and_exact_data_roundtrip(tmp_path):
    old=demo().to_dict()
    for k in OPTIONS:old['figure'].pop(k)
    p=from_dict(old);assert p.figure.legend_location=='best' and p.figure.minor_divisions==0
    original=copy.deepcopy(p.to_dict()['datasets']);session=Session(p)
    plan=session.preview([{'op':'set_figure','changes':OPTIONS}]);session.apply_review(plan)
    q=session.project;assert q.to_dict()['datasets']==original
    path=tmp_path/'edited.sps.json';save(q,path);assert load(path).to_dict()==q.to_dict()
    style=style_from_project(q);r=run_operations(p,[{'op':'apply_style','style':style}])
    for k,v in OPTIONS.items():assert getattr(r.figure,k)==v and templates.extract(q).figure[k]==v
    fig,ax,_,_=draw(q);assert ax.get_legend().get_frame_on() and ax.get_legend()._loc==2
    assert len(ax.xaxis.get_minorticklocs())>0
    session.undo();assert session.project.to_dict()['datasets']==original and session.project.figure.legend_location=='best'


@pytest.mark.parametrize('changes',[{'legend_location':'fake'},{'legend_frame':1},{'minor_divisions':True},{'minor_divisions':11},{'x_major_step':0},{'x_major_step':float('nan')},{'xscale':'log','x_major_step':1}])
def test_invalid_options_rejected_atomically(changes):
    p=demo();before=p.fingerprint()
    with pytest.raises(ValueError):run_operations(p,[{'op':'set_figure','changes':changes}])
    assert p.fingerprint()==before


def test_pptx_refuses_unmapped_new_style_without_output(tmp_path):
    p=demo();p.figure.annotations=[];p.figure.legend_location='upper left'
    out=tmp_path/'unsupported.pptx'
    with pytest.raises(ValueError,match='自定义图例/刻度'):pptx_io.export(p,out)
    assert not out.exists()


def test_gui_options_and_undo_preserve_data(window,app):
    w,errors=window;before=copy.deepcopy(w.project.to_dict()['datasets'])
    assert w.property_tabs.tabText(4)=='图例'
    for k in ('legend_location','legend_frame','x_major_step','y_major_step','minor_divisions'):
        value=OPTIONS[k]
        if k in ('x_major_step','y_major_step'):value=str(value)
        w.set_widget(w.fig_fields[k],value)
    w.apply_figure();assert not errors
    assert w.project.figure.legend_location=='upper left' and w.project.to_dict()['datasets']==before
    w.session.undo();w.refresh();assert w.project.figure.legend_location=='best'
