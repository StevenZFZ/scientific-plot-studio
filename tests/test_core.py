from dataclasses import asdict
import copy
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from sps.model import demo, Project, Series, Dataset, Annotation, save, load, from_dict, canonical
from sps.commands import Session, run_operations, style_from_project
from sps.data import import_table
from sps.render import export_bundle, preflight, font_info
from sps.bridge import capabilities, import_origin, export_origin


def test_editable_roundtrip_all_objects_and_audit(tmp_path):
    s = Session(demo())
    ops = [{"op": "set_series", "ids": ["series_ref"], "changes": {"kind": "errorbar", "y_error": "Error", "width": 2.3}},
           {"op": "add_annotation", "annotation": asdict(Annotation("text_a", "(a)", .1, .9))},
           {"op": "set_figure", "changes": {"xlim": [410, 840], "grid": True}}]
    s.execute(ops)
    path = tmp_path / "sample.sps.json"
    save(s.project, path)
    recovered = load(path)
    assert recovered.to_dict() == s.project.to_dict()
    assert recovered.fingerprint() == s.project.fingerprint()
    assert recovered.figure.series[0].y_error == "Error"
    assert recovered.figure.annotations[0].text == "(a)"
    assert recovered.audit[0]["operations"] == ops
    # Same renderer, exact same RGBA pixels before and after native roundtrip.
    a, _ = preflight(s.project, 100)
    b, _ = preflight(recovered, 100)
    assert np.array_equal(np.asarray(a.canvas.buffer_rgba()), np.asarray(b.canvas.buffer_rgba()))


def test_csv_import_explicit_mapping_and_provenance(tmp_path):
    source = tmp_path / "actual.csv"
    original = b"Time,Stress,Error\n1,3,0.1\n2,5,0.2\n"
    source.write_bytes(original)
    d = import_table(source)
    p = Project(datasets=[d])
    s = Series("curve", d.id, "Time", "Stress", kind="errorbar", y_error="Error")
    session = Session(p)
    session.execute([{"op": "add_series", "series": asdict(s)},
                     {"op": "set_cell", "dataset": d.id, "column": "Stress", "row": 0, "value": 4.5}])
    assert session.project.datasets[0].columns["Stress"] == [4.5, 5]
    assert len(d.source_sha256) == 64
    assert not d.synthetic
    assert source.read_bytes() == original
    session.undo()
    assert not session.project.figure.series


@pytest.mark.parametrize("body", ["x,x\n1,2", "x,y\n1,", "x,y\n1,nan", "x,y\n1,inf", "x,y\n1,2,3", "x,y\n"])
def test_invalid_csv_rejected_without_silent_point_loss(tmp_path, body):
    p = tmp_path / "bad.csv"
    p.write_text(body)
    with pytest.raises(ValueError):
        import_table(p)


def test_tsv_bom(tmp_path):
    p = tmp_path / "table.tsv"
    p.write_text("\ufeffx\ty\n1\t2\n", encoding="utf-8")
    assert import_table(p).columns == {"x": [1], "y": [2]}


def test_transaction_rollback_undo_redo_append_only_audit():
    s = Session(demo())
    initial = s.project.fingerprint()
    with pytest.raises(ValueError):
        s.execute([{"op": "set_figure", "changes": {"grid": True}},
                   {"op": "set_series", "ids": ["missing"], "changes": {"width": 2}}])
    assert s.project.fingerprint() == initial
    assert not s._undo
    s.execute([{"op": "set_series", "ids": ["series_ref", "series_mod"], "changes": {"width": 2.5}}])
    assert all(x.width == 2.5 for x in s.project.figure.series)
    assert s.undo()
    assert all(x.width == 1.6 for x in s.project.figure.series)
    assert s.redo()
    assert all(x.width == 2.5 for x in s.project.figure.series)
    assert [a["action"] for a in s.project.audit] == ["transaction", "undo", "redo"]


def test_review_read_only_stale_and_tamper_protection():
    session = Session(demo())
    before = session.project.fingerprint()
    plan = session.preview([{"op": "set_figure", "changes": {"font_size": 12}}])
    assert session.project.fingerprint() == before
    assert plan["changes"] == [{"path": "/figure/font_size", "before": 10, "after": 12}]
    bad = copy.deepcopy(plan)
    bad["operations"][0]["changes"]["font_size"] = 20
    with pytest.raises(ValueError, match="更改"):
        session.apply_review(bad)
    session.apply_review(plan)
    assert session.project.figure.font_size == 12
    with pytest.raises(ValueError, match="过期"):
        session.apply_review(plan)


@pytest.mark.parametrize("op", [
    {"op": "exec", "code": "print('bad')"},
    {"op": "set_figure", "changes": {"__class__": "bad"}},
    {"op": "set_figure", "changes": {"font_size": float("nan")}},
    {"op": "set_figure", "changes": {"width_mm": 0}},
    {"op": "set_figure", "changes": {"xscale": "log", "xlim": [0, 1]}},
    {"op": "set_series", "ids": ["series_ref"], "changes": {"color": "red"}},
    {"op": "set_series", "ids": ["series_ref"], "changes": {"kind": "errorbar"}},
    {"op": "set_figure", "changes": {"grid": "false"}},
    {"op": "set_figure", "changes": {"title": "x"}, "extra": 1},
])
def test_allowlist_and_validation(op):
    with pytest.raises(ValueError):
        run_operations(demo(), [op])


def test_style_transfer_preserves_scientific_content_and_review(tmp_path):
    source = demo()
    source.figure.font_size = 13
    source.figure.series[0].color = "#112233"
    style = style_from_project(source)
    target = demo()
    target.figure.xlabel = "Different scientific axis"
    target.figure.xlim = [420, 800]
    data_before = copy.deepcopy(target.datasets)
    session = Session(target)
    plan = session.preview([{"op": "apply_style", "style": style}])
    assert session.project.figure.font_size == 10
    session.apply_review(plan)
    assert session.project.figure.font_size == 13
    assert session.project.figure.series[0].color == "#112233"
    assert session.project.figure.xlabel == "Different scientific axis"
    assert session.project.figure.xlim == [420, 800]
    assert session.project.datasets == data_before


@pytest.mark.parametrize("kind", ["line", "scatter", "bar", "errorbar"])
def test_plot_types_render(kind):
    p = demo()
    p.figure.series[0].kind = kind
    if kind == "errorbar":
        p.figure.series[0].y_error = "Error"
    fig, info = preflight(p, 100)
    assert info["passed"]
    assert np.asarray(fig.canvas.buffer_rgba()).std() > 0


def test_log_axis_rejects_nonpositive_data():
    p = demo()
    p.datasets[0].columns["Reference"][0] = 0
    with pytest.raises(ValueError, match="对数"):
        run_operations(p, [{"op": "set_figure", "changes": {"yscale": "log"}}])


def test_font_and_crop_fail_closed():
    p = demo()
    p.figure.font = "SPS_NoSuchFont_123"
    with pytest.raises(ValueError, match="未安装"):
        preflight(p)
    p = demo()
    p.figure.title = "中文标题"
    with pytest.raises(ValueError, match="缺少字符"):
        preflight(p)
    p = demo()
    p.figure.annotations.append(Annotation("long", "TOO LONG " * 20, .9, .5))
    with pytest.raises(ValueError, match="超出画布"):
        preflight(p)


def test_four_export_formats_dimensions_alpha_embedded_fonts_and_source_unchanged(tmp_path):
    p = demo()
    before = p.fingerprint()
    report = export_bundle(p, tmp_path, "publication", dpi=150)
    assert p.fingerprint() == before
    assert {x["format"] for x in report["files"]} == {"png", "svg", "pdf", "tiff"}
    assert all(x["passed"] for x in report["files"])
    assert report["preflight"]["text_bounds"] == "inside_canvas"
    assert len(report["preflight"]["font"]["sha256"]) == 64
    pdf = next(x for x in report["files"] if x["format"] == "pdf")
    assert pdf["fonts"] and all(x["embedded"] for x in pdf["fonts"])
    png = next(x for x in report["files"] if x["format"] == "png")
    assert png["alpha_extrema"] == [0, 255]
    with Image.open(tmp_path / "publication.png") as a, Image.open(tmp_path / "publication.tiff") as b:
        assert np.array_equal(np.array(a.convert("RGBA")), np.array(b.convert("RGBA")))
    assert json.loads((tmp_path / "publication.export.json").read_text())["project_hash"] == before
    with pytest.raises(FileExistsError):
        export_bundle(p, tmp_path, "publication")


def test_opaque_background_and_no_export_on_preflight_failure(tmp_path):
    p = demo()
    report = export_bundle(p, tmp_path, "opaque", ["png"], 100, transparent=False)
    assert report["files"][0]["alpha_extrema"] == [255, 255]
    p.figure.font = "UnavailableFont123"
    with pytest.raises(ValueError):
        export_bundle(p, tmp_path, "bad")
    assert not list(tmp_path.glob("bad.*"))


@pytest.mark.parametrize("data", [{}, {"schema": "sps.project/99"}, {"schema": "sps.project/1", "executable": "evil"}])
def test_schema_rejects_unsupported_and_unknown(data):
    with pytest.raises(ValueError):
        from_dict(data)


def test_bridge_honest_and_no_fake_output(tmp_path):
    c = capabilities()
    assert not c["opj_import"] and not c["opju_export"]
    with pytest.raises(NotImplementedError):
        import_origin(tmp_path / "sample.opju")
    with pytest.raises(NotImplementedError):
        export_origin(demo(), tmp_path / "fake.opju")
    assert not (tmp_path / "fake.opju").exists()
