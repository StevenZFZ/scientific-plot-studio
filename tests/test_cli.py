import json
from pathlib import Path
import subprocess
import sys

from sps.model import demo, save, load


def cli(*args):
    return subprocess.run([sys.executable, "-m", "sps", *map(str, args)], capture_output=True, text=True)


def test_cli_review_apply_export_and_stale_rejection(tmp_path):
    source = tmp_path / "source.sps.json"
    edited = tmp_path / "edited.sps.json"
    ops = tmp_path / "ops.json"
    review = tmp_path / "review.json"
    assert cli("demo", source).returncode == 0
    before = source.read_bytes()
    ops.write_text(json.dumps([{"op": "set_figure", "changes": {"font_size": 12}}]))
    assert cli("review", source, ops, review).returncode == 0
    assert source.read_bytes() == before
    assert cli("apply", source, review, edited).returncode == 0
    assert load(edited).figure.font_size == 12
    assert cli("apply", edited, review, tmp_path / "bad.sps.json").returncode == 2
    assert not (tmp_path / "bad.sps.json").exists()
    assert cli("export", edited, tmp_path / "exports", "--dpi", "100").returncode == 0
    assert (tmp_path / "exports" / "figure.export.json").exists()
    bridge = json.loads(cli("bridge").stdout)
    assert bridge["opj_import"] is False
