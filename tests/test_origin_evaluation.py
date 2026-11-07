"""Evaluation utilities use generated signatures/dumps; no private samples in CI."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import pytest
from scripts.origin_corpus import evaluate, signature, summarize_probe
from scripts.origin_data_fixture import numeric_pair


def column(role, data):
    return {'type_raw': role, 'sheet_raw': 0, 'data': data}


def test_corpus_inventory_hashes_unicode_boundary_and_no_overwrite(tmp_path):
    root = tmp_path/'工作二'
    root.mkdir()
    legacy = root/'test.opj'; legacy.write_bytes(b'CPYA 4.3074 215 W64 #\nfixture')
    unicode = root/'test.opju'; unicode.write_bytes(b'CPYUA 4.3748 212\nfixture')
    (root/'wrong.opj').write_bytes(b'Not an Origin project')
    (root/'ignored.csv').write_bytes(b'x,y\n1,2')
    (root/'link.opj').symlink_to(legacy)
    before = {f.name: f.read_bytes() for f in root.iterdir() if f.is_file()}
    output = tmp_path/'results'
    report = evaluate([root], output)
    assert report['summary']['files'] == 3
    assert report['summary']['all_sources_unchanged']
    assert report['summary']['sps_import'] == {'unsupported': 3}
    assert signature(legacy)['family'] == 'legacy_opj'
    assert signature(unicode)['family'] == 'unicode_opju'
    assert {f.name:f.read_bytes() for f in root.iterdir() if f.is_file()} == before
    assert json.loads((output/'corpus.json').read_text()) == report
    with pytest.raises(FileExistsError): evaluate([root], output)
    with pytest.raises(ValueError): evaluate([root], root/'bad-output')
    assert not (root/'bad-output').exists()


def test_corpus_cli_runs_with_no_native_parser(tmp_path):
    root=tmp_path/'samples';root.mkdir()
    (root/'test.opju').write_bytes(b'CPYUA 4.3748 212\nfixture')
    script=Path(__file__).resolve().parents[1]/'scripts/origin_corpus.py'
    result=subprocess.run([sys.executable,str(script),'--root',str(root),'--output',str(tmp_path/'out')],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
    assert json.loads(result.stdout)['native_probe'] == {'unsupported_opju_not_sent_to_legacy_parser':1}


def test_probe_summary_includes_excel_and_missing_without_silent_cleaning():
    data={'schema':'sps.experimental.origin-probe/1','counts':{'excels':1},
          'spreads':[{'columns':[{'data':[1.,None,{'text_hex':'3330'}]}]}],
          'excels':[{'sheets':[{'columns':[{'data':[2.,3.]}]}]}],
          'graphs':[{'layers':[{'curves':[{'type_raw':200}]},{'curves':[]}]}]}
    before=copy.deepcopy(data)
    result=summarize_probe(data)
    assert result['columns_dumped']==2
    assert result['cells']=={'numeric':3,'missing_or_nonfinite':1,'text':1}
    assert result['multi_layer_graphs']==1 and result['curves']==1
    assert data == before
    data['spreads'][0]['columns'][0]['data'].append(float('nan'))
    with pytest.raises(ValueError): summarize_probe(data)


@pytest.mark.parametrize('bad_y',[[None,2],[{'text_hex':'31'},2],[float('inf'),2],[2],[]])
def test_numeric_fixture_refuses_missing_text_nonfinite_or_truncation(bad_y):
    sheet={'columns':[column(0,[1,2]),column(1,bad_y)]}
    with pytest.raises(ValueError): numeric_pair(sheet,0,1)


def test_numeric_fixture_copies_exact_finite_vectors_and_checks_roles():
    sheet={'columns':[column(0,[1.2345678901234567,2]),column(1,[3.141592653589793,5])]}
    before=copy.deepcopy(sheet)
    x,y=numeric_pair(sheet,0,1)
    assert x==before['columns'][0]['data'] and y==before['columns'][1]['data']
    x[0]=99;assert sheet==before
    with pytest.raises(ValueError):numeric_pair(sheet,1,0)
    with pytest.raises(ValueError):numeric_pair(sheet,-1,0)
    sheet['columns'][1]['sheet_raw']=1
    with pytest.raises(ValueError):numeric_pair(sheet,0,1)
