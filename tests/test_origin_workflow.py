import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from sps import origin,templates
from sps.model import demo,load,save
from sps.commands import Session,run_operations


def hextext(s):return s.encode().hex()


def probe_fixture():
    curve={'type_raw':200,'line_color':{'type_raw':3,'rgb_raw':[242,121,112]},
           'line_width_raw':3.0,'line_style_raw':0,'line_connect_raw':1,
           'symbol_shape_raw':0,'symbol_size_raw':9}
    layer={'curves':[curve,copy.deepcopy(curve)],'x_axis':{'scale_raw':0,'tick_font_size_raw':18},
           'y_axis':{'scale_raw':0,'tick_font_size_raw':18},'legend_hex':hextext(r'\l(1) %(1)')}
    return {'schema':'sps.experimental.origin-probe/1','liborigin':'fixture',
            'graphs':[{'name_hex':hextext('Graph1'),'template_name_hex':hextext('LINE'),
                       'is3d':False,'is_layout':False,'layers':[layer,copy.deepcopy(layer)]}],
            'spreads':[{'columns':[{'data':['PRIVATE_VALUE_MUST_NOT_BE_COPIED']}]}]}


def analysis_fixture():return origin.analyze_probe(probe_fixture(),{'name':'fixture.opj','sha256':'a'*64,'bytes':256})


def test_origin_analysis_has_evidence_counts_and_no_worksheet_or_script():
    raw=probe_fixture();before=copy.deepcopy(raw);r=origin.analyze_probe(raw)
    assert raw==before
    assert r['counts']=={'graphs':1,'layers':2,'curves':4,'multi_layer_graphs':1}
    assert r['statistics']['width']['observed']==r['statistics']['width']['total']==4
    assert r['statistics']['color']['frequencies']==[{'value':'#f27970','count':4}]
    assert 'PRIVATE_VALUE_MUST_NOT_BE_COPIED' not in json.dumps(r)
    assert '原图保真' in origin.markdown(r)
    assert origin.validate_report(r)==r
    r['layers'][0]['curves'][0]['style']['width']=1
    with pytest.raises(ValueError,match='摘要'):origin.validate_report(r)


def test_partial_style_preserves_science_and_empty_palette_positions():
    r=analysis_fixture();r['layers'][0]['curves'][0]['style']={};r=origin.seal(r)
    style=origin.layer_style(r,'g1:l1')
    p=demo();before=copy.deepcopy(p.to_dict());session=Session(p)
    review=session.preview([{'op':'apply_style','style':style}])
    assert session.project.to_dict()==before
    session.apply_review(review)
    assert session.project.datasets==p.datasets
    assert session.project.figure.series[0].width==p.figure.series[0].width
    assert session.project.figure.series[1].width==3
    assert session.project.figure.xlabel==p.figure.xlabel
    assert session.project.figure.xlim==p.figure.xlim
    session.undo();assert session.project.figure==p.figure
    session.redo();assert session.project.figure.series[1].width==3
    with pytest.raises(ValueError):run_operations(p,[{'op':'apply_style','style':{'schema':'sps.style/1','figure':{},'series':[{}]}}])


def test_partial_template_explicit_provenance_roundtrip_and_rebind(tmp_path):
    r=analysis_fixture();t=origin.layer_template(r,'g1:l1')
    assert t.schema=='sps.template/2' and t.source['kind']=='origin_partial' and t.source['source_sha256']=='a'*64
    assert '其他层未迁移' in t.description
    dest=tmp_path/'partial.sps-template.json';templates.save(t,dest)
    assert templates.load(dest)==t
    p=demo();binding=[{'slot':s.id,'dataset':p.datasets[0].id,'x':'Wavelength','y':y,'y_error':''}
                     for s,y in zip(t.slots,['Reference','Modified'])]
    q=templates.instantiate(p,t.to_dict(),binding,{'title':'Explicit','x_label':p.figure.xlabel,'y_label':p.figure.ylabel})
    assert q.series[0].color=='#f27970' and q.series[0].width==3
    assert q.xlim is None and not q.annotations
    legacy=t.to_dict();legacy['schema']='sps.template/1'
    with pytest.raises(ValueError,match='sps.template/2'):templates.from_dict(legacy)
    assert templates.extract(p).schema=='sps.template/1'
    data=t.to_dict();data['source']['source_sha256']='missing'
    with pytest.raises(ValueError):templates.from_dict(data)


@pytest.mark.parametrize('plot_type',[201,202,203,231,103])
def test_partial_template_refuses_unmapped_structure(plot_type):
    raw=probe_fixture();raw['graphs'][0]['layers'][0]['curves'][0]['type_raw']=plot_type
    r=origin.analyze_probe(raw,{'name':'fixture','sha256':'a'*64})
    with pytest.raises(ValueError):origin.layer_template(r,'g1:l1')


def test_bad_color_and_width_not_guessed():
    raw=probe_fixture();c=raw['graphs'][0]['layers'][0]['curves'][0]
    c['line_color']={'type_raw':2,'index_raw':4};c['line_width_raw']=float('inf')
    r=origin.analyze_probe(raw);c=r['layers'][0]['curves'][0]
    assert 'color' not in c['style'] and 'width' not in c['style'] and c['issues']
    assert r['statistics']['color']['observed']==3


def test_opju_header_rejected_even_if_renamed(tmp_path):
    f=tmp_path/'bad.opj';f.write_bytes(b'CPYUA 4.3748 212\nfixture')
    with pytest.raises(ValueError,match='OPJU'):origin.inspect(f,sys.executable)
    assert f.read_bytes()==b'CPYUA 4.3748 212\nfixture'


def test_cli_style_template_and_offline_plan_to_real_exports(tmp_path):
    def cli(*args):
        r=subprocess.run([sys.executable,'-m','sps',*map(str,args)],text=True,capture_output=True)
        assert r.returncode==0,r.stderr
        return r
    analysis=tmp_path/'analysis.json';analysis.write_text(json.dumps(analysis_fixture()))
    style=tmp_path/'style.json';template=tmp_path/'partial.sps-template.json'
    cli('origin-style',analysis,'g1:l1',style);cli('origin-template',analysis,'g1:l1',template)
    p=demo();source=tmp_path/'source.sps.json';save(p,source)
    review=tmp_path/'review.json';plan=tmp_path/'ai-plan.json'
    cli('ai-plan',source,plan,'--offline','reference','--style',style,'--review-output',review)
    result=tmp_path/'result.sps.json';cli('apply',source,review,result)
    assert load(result).datasets==p.datasets
    assert load(result).figure.series[0].color=='#f27970'
    cli('export',result,tmp_path/'exports','--dpi','100')
    assert (tmp_path/'exports/figure.export.json').exists()
