"""Writable local state; native app builds must not write into signed resources."""
import os,sys
from pathlib import Path


def data_dir():
    configured=os.environ.get('SPS_DATA_ROOT')
    if configured:return Path(configured)
    if sys.platform=='darwin':return Path.home()/'Library/Application Support/ScientificPlotStudio'
    if sys.platform=='win32':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'ScientificPlotStudio'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'ScientificPlotStudio'
