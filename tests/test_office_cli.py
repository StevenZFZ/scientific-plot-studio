import json,subprocess,sys
from pathlib import Path
from sps.model import demo,save,load
from test_office import ppt_fixture,recovery_fixture


def cli(*args):return subprocess.run([sys.executable,'-m','sps',*map(str,args)],capture_output=True,text=True)


def test_office_cli_roundtrips_and_no_overwrite(tmp_path):
    source=tmp_path/'source.sps.json';p=demo();p.figure.annotations=[];save(p,source)
    ppt=tmp_path/'figure.pptx';assert cli('pptx-export',source,ppt).returncode==0
    restored=tmp_path/'restored.sps.json';assert cli('pptx-recover',ppt,restored).returncode==0
    assert load(restored).to_dict()==p.to_dict()
    assert cli('pptx-export',source,ppt).returncode==2
    origin=tmp_path/'origin.pptx';ppt_fixture(origin,b'CPYUA 4.3\nfixture')
    report=tmp_path/'scan.json';assert cli('office-scan',origin,report).returncode==0
    assert json.loads(report.read_text())['counts']['opju']==1
    directory=tmp_path/'extracted';assert cli('office-extract',origin,directory).returncode==0
    assert (directory/'recovery.json').exists()
    raw=tmp_path/'sample.opj';raw.write_bytes(b'CPYA 4.3 #\nfixture')
    probe=tmp_path/'probe';data=recovery_fixture()['probe']
    probe.write_text(f'#!{sys.executable}\nimport sys,json\nopen(sys.argv[2],"w").write(json.dumps({data!r}))\n');probe.chmod(0o700)
    output=tmp_path/'data';r=cli('origin-data',raw,output,'--probe',probe,'--pair','0:0:1','--xlabel','X unit')
    assert r.returncode==0,r.stderr
    recovered=load(output/'data-only.sps.json');assert recovered.datasets[0].columns['X']==[1.,1.0000000000000002]
    assert recovered.figure.xlabel=='X unit' and json.loads((output/'recovery.json').read_text())['probe']==data
    before=(output/'data-only.sps.json').read_bytes()
    assert cli('origin-data',raw,output,'--probe',probe,'--pair','0:0:1').returncode==2
    assert (output/'data-only.sps.json').read_bytes()==before
