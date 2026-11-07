"""Publication policies use synthetic curves and explicit final-size checks."""
import copy,json
import pytest
from sps.model import demo,Project,FigureSpec,GraphPage,GraphLayer,Dataset,Series,save,load
from sps.publication import operation,framed_sides,effective_sides,PROFILES,inspect_pages,batch_import
from sps.commands import Session,run_operations
from sps.render import draw,preflight,export_bundle


def test_framed_axes_have_only_active_side_ticks_and_independent_labels():
    p=demo();p.figure.axis_sides=framed_sides();fig,ax,*_=draw(p)
    assert all(s.get_visible()for s in ax.spines.values())
    assert all(not t.tick2line.get_visible()and not t.label2.get_visible()for t in ax.xaxis.get_major_ticks()+ax.yaxis.get_major_ticks())
    assert all(t.tick1line.get_visible()for t in ax.xaxis.get_major_ticks()+ax.yaxis.get_major_ticks())
    p.figure.axis_sides['right']={'spine':True,'ticks':True,'labels':True}
    _,ax,*_=draw(p);assert ax.yaxis.get_major_ticks()[0].label2.get_visible()
    p.figure.axis_sides['top']={'spine':False,'ticks':False,'labels':False}
    assert not draw(p)[1].spines['top'].get_visible()


def test_legacy_defaults_preserve_payload_and_behavior():
    p=demo();payload=p.to_dict()
    assert not {'axis_sides','layout_mode','label_wrap'}&payload['figure'].keys()
    p.figure.box=True;assert effective_sides(p.figure)['right']['ticks']
    p.figure.box=False;assert not effective_sides(p.figure)['right']['spine']
    with pytest.raises(ValueError):run_operations(p,[{'op':'set_figure','changes':{'axis_sides':{'left':True}}}])


def test_uniform_final_size_retains_numbers_curve_styles_ranges_and_undo(tmp_path):
    p=demo();p.figure.xlim=[0,10];p.figure.ylim=[0,100]
    original=copy.deepcopy(p.to_dict());session=Session(p)
    session.execute([operation(profile='nano_letters',font='DejaVu Sans')])
    q=session.project;f=q.figure
    assert f.width_mm==pytest.approx(240/72*25.4)
    assert f.font_size==f.xlabel_size==f.ylabel_size==f.tick_size==f.legend_size==8
    assert q.datasets==p.datasets and f.series==p.figure.series
    assert f.xlim==[0,10]and f.ylim==[0,100]
    assert q.name==p.name and f.xlabel==p.figure.xlabel
    path=tmp_path/'pub.sps.json';save(q,path);assert load(path).to_dict()==q.to_dict()
    assert session.undo();assert session.project.datasets==p.datasets and session.project.figure==p.figure
    assert p.to_dict()==original


def test_long_axis_title_wraps_without_changing_source_or_shrinking_font(tmp_path):
    p=demo();p.figure.xlabel='Applied tensile strain under a repeated controlled loading cycle (%)'
    p.figure.ylabel='Measured normalized electrical response (%)'
    p=run_operations(p,[operation(font='DejaVu Sans')]);fig,report=preflight(p,150)
    assert report['passed']and '\n'in fig.axes[0].get_xlabel()
    assert p.figure.xlabel=='Applied tensile strain under a repeated controlled loading cycle (%)'
    assert fig.axes[0].xaxis.label.get_fontsize()==7
    output=export_bundle(p,tmp_path/'exports','normal',['png','svg','pdf','tiff'],150,True)
    assert len(output['files'])==4


def test_overcrowded_category_ticks_are_not_silently_approved():
    d=Dataset('d','synthetic',{'X':list(range(10)),'Y':list(range(10))})
    f=FigureSpec(series=[Series('s','d','X','Y')],xtick_values=list(range(10)),xtick_labels=['Long condition '+str(i)for i in range(10)])
    p=run_operations(Project(datasets=[d],figure=f),[operation(font='DejaVu Sans')])
    checks=inspect_pages(p);assert not checks[0]['passed']
    assert '刻度' in checks[0]['error']or '超出'in checks[0]['error']
    assert all(v==7 for v in (p.figure.xlabel_size,p.figure.tick_size))


def test_multilayer_keeps_secondary_scale_and_geometry():
    p=demo();f=copy.deepcopy(p.figure);f.series[0].id='alt1';f.series[1].id='alt2'
    f.axis_sides=framed_sides();f.axis_sides['right']['labels']=True
    page=GraphPage('g','Dual',[GraphLayer('l1','Main',p.figure,[.2,.2,.6,.6]),GraphLayer('l2','Right',f,[.2,.2,.6,.6])])
    p=Project(datasets=p.datasets,pages=[page]);before=copy.deepcopy(page)
    q=run_operations(p,[operation(font='DejaVu Sans')])
    assert [l.rect for l in q.pages[0].layers]==[l.rect for l in before.layers]
    assert q.pages[0].layers[1].figure.axis_sides==before.layers[1].figure.axis_sides
    assert q.pages[0].issues and q.pages[0].layers[0].figure.layout_mode=='source'


def test_batch_files_isolated_failures_no_overwrite_or_source_mutation(tmp_path,monkeypatch):
    from sps import origin_graphs
    sources=[tmp_path/'one.opju',tmp_path/'bad.opju',tmp_path/'three.opju']
    for p in sources:p.write_bytes(b'synthetic original')
    def read(source,*args):
        if source.name=='bad.opju':raise ValueError('unsupported synthetic')
        return {'project':demo(),'error':None}
    monkeypatch.setattr(origin_graphs,'read_project',read)
    opts={'profile':'nature','size':'single','font':'DejaVu Sans','scope':'all'}
    out=tmp_path/'results';r=batch_import(sources,out,opts)
    assert [f['status']for f in r['files']]==['saved','failed','saved']
    assert all(p.read_bytes()==b'synthetic original'for p in sources)
    assert len(list(out.glob('*.sps.json')))==2
    assert json.loads((out/'batch-report.json').read_text())['files'][1]['error']=='unsupported synthetic'
    with pytest.raises(FileExistsError):batch_import(sources,out,opts)


def test_unicode_scripts_use_explicit_font_without_losing_source(tmp_path):
    from matplotlib.font_manager import fontManager
    p=demo();p.figure.ylabel='ΔR/R₀ (%)';p.figure.xlabel='Temperature (℃)'
    font='Arial'if any(f.name=='Arial'for f in fontManager.ttflist)else'DejaVu Sans'
    q=run_operations(p,[operation(font=font)])
    fig,report=preflight(q,100)
    assert report['font']['family']==font
    assert q.figure.ylabel=='ΔR/R₀ (%)'and q.figure.xlabel=='Temperature (℃)'
    assert r'$_{\mathregular{0}}$'in fig.axes[0].get_ylabel()and '°C'in fig.axes[0].get_xlabel()
    output=export_bundle(q,tmp_path/'exports','scripts',['pdf','svg'],100,True)
    assert len(output['files'])==2
    if font=='Arial':
        pdf=next(f for f in output['files']if f['format']=='pdf')
        assert all('Arial'in f['name']for f in pdf['fonts']),pdf['fonts']


def test_empty_hidden_origin_helper_does_not_block_framed_main_axes():
    p=demo();page=GraphPage('g','Origin',[GraphLayer('main','1',p.figure,[.1,.1,.8,.8]),GraphLayer('helper','TopXRightY',FigureSpec(),[.1,.1,.8,.8],axes_visible=False)])
    p=run_operations(Project(datasets=p.datasets,pages=[page]),[operation(font='DejaVu Sans')])
    assert p.figure.axis_sides==framed_sides()and p.figure.layout_mode=='auto'
    fig,*_=draw(p);assert len(fig.axes)==2 and not fig.axes[1].axison
    assert fig.axes[0].spines['top'].get_visible()
    assert not fig.axes[0].xaxis.get_major_ticks()[0].tick2line.get_visible()
    assert preflight(p,100)[1]['passed']
