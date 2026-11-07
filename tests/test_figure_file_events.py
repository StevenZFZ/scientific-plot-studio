import os,subprocess,sys


def test_explicit_data_root_unifies_source_and_native_cache(monkeypatch,tmp_path):
    from sps.local_paths import data_dir
    from sps.figure_links import root_dir
    monkeypatch.setenv('SPS_DATA_ROOT',str(tmp_path/'state'))
    assert data_dir()==tmp_path/'state'
    assert root_dir()==tmp_path/'state/figure-links'


def test_native_file_and_url_events_queue_before_window_and_dispatch_after_ready():
    script='''from PySide6.QtGui import QFileOpenEvent
from PySide6.QtCore import QUrl
from sps.gui import SPSApplication
app=SPSApplication([])
app.event(QFileOpenEvent('/tmp/synthetic.spsfig'))
assert app.pending_files==['/tmp/synthetic.spsfig']
received=[];app.fileRequested.connect(received.append);app.ready=True
app.event(QFileOpenEvent(QUrl('spsfigure://edit/11111111-1111-4111-8111-111111111111')))
assert received==['spsfigure://edit/11111111-1111-4111-8111-111111111111']
'''
    result=subprocess.run([sys.executable,'-c',script],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
