from dataclasses import asdict
import copy
import json
import subprocess
import sys

import pytest

from sps.model import demo, Dataset, Project, Annotation, save as save_project, load as load_project
from sps.commands import Session, run_operations
from sps import templates
from sps.render import preflight
from sps.review import review_rows


def target_data(ident="new_data", multiplier=1):
    return Dataset(ident, "Explicit new data", {"Time": [1., 2., 3.], "Force A": [2. * multiplier, 3. * multiplier, 4. * multiplier],
                                               "Force B": [3., 4., 5.], "Error": [.1, .2, .3]}, synthetic=True)


def operation(template, d):
    return {"op": "apply_template", "template": template.to_dict(),
            "bindings": [{"slot": slot.id, "dataset": d.id, "x": "Time", "y": "Force A" if i == 0 else "Force B",
                          "y_error": "Error" if slot.properties.get("kind") == "errorbar" else ""}
                         for i, slot in enumerate(template.slots)],
            "labels": {"title": "New data", "x_label": "Time (s)", "y_label": "Force (N)"}}


def test_template_roundtrip_rebind_two_datasets_preserves_all_numbers_and_undo(tmp_path):
    original = demo()
    original.figure.xlim = [400, 850]
    original.figure.annotations = [Annotation("note", "{{title}}", .1, .9)]
    template = templates.extract(original, "Personal reusable template")
    assert template.figure["xlim"] is None
    assert templates.extract(original, keep_ranges=True).figure["xlim"] == [400, 850]
    file = tmp_path / "plot.sps-template.json"
    templates.save(template, file)
    assert templates.load(file).to_dict() == template.to_dict()
    assert "columns" not in file.read_text() and "Wavelength" not in file.read_text()
    p = Project(name="New project", datasets=[target_data(), target_data("second", 10)])
    before = copy.deepcopy(p.datasets)
    session = Session(p)
    plan = session.preview([operation(template, p.datasets[0])])
    assert session.project.figure.series == []
    session.apply_review(plan)
    assert session.project.datasets == before
    assert session.project.figure.series[0].label == "Force A"
    assert session.project.figure.annotations[0].text == "New data"
    assert session.project.figure.xlabel == "Time (s)"
    first_figure = copy.deepcopy(session.project.figure)
    second_op = operation(template, p.datasets[1])
    second_op["labels"]["title"] = "Second data"
    session.apply_review(session.preview([second_op]))
    assert session.project.datasets == before
    assert session.project.figure.series[0].dataset == "second"
    assert session.project.figure.annotations[0].text == "Second data"
    preflight(session.project, 100)
    session.undo()
    assert session.project.figure == first_figure
    session.redo()
    save_project(session.project, tmp_path / "result.sps.json")
    assert load_project(tmp_path / "result.sps.json").to_dict() == session.project.to_dict()


def test_template_review_is_deterministic_atomic_and_no_hidden_data_mutation():
    p = demo()
    t = templates.builtin_templates()[1]
    d = target_data()
    p.datasets.append(d)
    s = Session(p)
    op = operation(t, d)
    plan = s.preview([op])
    assert s.preview([op]) == plan
    rows = review_rows(p, [op])
    assert len(rows) == 1 and "套用模板" in rows[0]["label"]
    assert len(rows[0]["operations"]) == 1
    before = p.to_dict()
    bad = copy.deepcopy(op)
    bad["bindings"][0]["x"] = "does not exist"
    with pytest.raises(ValueError):
        s.execute([{"op": "set_figure", "changes": {"grid": True}}, bad])
    assert s.project.to_dict() == before
    s.apply_review(plan)
    assert s.project.audit[-1]["operations"][0]["bindings"] == op["bindings"]


@pytest.mark.parametrize("change", [
    lambda x: x.update(schema="sps.template/99"),
    lambda x: x.update(layers=[{}]),
    lambda x: x["source"].update(kind="origin_bridge"),
    lambda x: x["slots"][0]["properties"].update(dataset="secret"),
    lambda x: x["slots"].append(copy.deepcopy(x["slots"][0])),
    lambda x: x["figure"].update(xlabel="{{execute_code}}"),
    lambda x: x["figure"].update(width_mm=float("inf")),
    lambda x: x.update(annotations=[{"text": "x", "script": "bad"}]),
])
def test_unknown_or_invalid_template_rejected(change):
    data = templates.builtin_templates()[0].to_dict()
    change(data)
    with pytest.raises(ValueError):
        templates.from_dict(data)


def test_error_roles_required_and_no_implicit_column_inference():
    t = templates.builtin_templates()[2]
    d = target_data()
    p = Project(datasets=[d])
    op = operation(t, d)
    op["bindings"][0]["y_error"] = ""
    with pytest.raises(ValueError, match="误差列"):
        run_operations(p, [op])
    op["bindings"][0]["y_error"] = "Error"
    assert run_operations(p, [op]).figure.series[0].kind == "errorbar"
    op["labels"].pop("y_label")
    with pytest.raises(ValueError, match="单位"):
        run_operations(p, [op])


def test_library_dedup_corrupt_file_visibility_and_fake_origin_rejection(tmp_path):
    library = templates.TemplateLibrary(tmp_path)
    t = templates.builtin_templates()[0]
    path = library.add(t)
    assert library.add(t) == path
    assert len(list(tmp_path.glob("*.json"))) == 1
    (tmp_path / "bad.sps-template.json").write_text('{}')
    assert len(library.items()) == len(templates.builtin_templates()) + 1
    assert library.errors and "bad" in library.errors[0]
    origin = tmp_path / "sample.otpu"
    origin.write_bytes(b"not a real template")
    with pytest.raises(ValueError, match="Origin"):
        templates.load(origin)
    with pytest.raises(ValueError, match="伪装"):
        templates.save(t, origin)
    assert origin.read_bytes() == b"not a real template"


def test_builtin_previews_are_synthetic_and_render():
    for t in templates.builtin_templates():
        p = templates.preview_project(t)
        assert all(d.synthetic for d in p.datasets)
        assert len(p.figure.series) == len(t.slots)
        preflight(p, 100)


def test_cli_template_extraction_review_apply_and_export(tmp_path):
    def cli(*args):
        result = subprocess.run([sys.executable, "-m", "sps", *map(str, args)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result
    source = tmp_path / "source.sps.json"
    target = tmp_path / "target.sps.json"
    template_file = tmp_path / "line.sps-template.json"
    result_file = tmp_path / "result.sps.json"
    bindings_file = tmp_path / "bindings.json"
    plan_file = tmp_path / "review.json"
    save_project(demo(), source)
    cli("template-extract", source, template_file, "--name", "Native template")
    t = templates.load(template_file)
    d = target_data()
    p = Project(datasets=[d])
    save_project(p, target)
    op = operation(t, d)
    bindings_file.write_text(json.dumps({k: op[k] for k in ("bindings", "labels")}))
    before = target.read_bytes()
    cli("template-review", target, template_file, bindings_file, plan_file)
    assert target.read_bytes() == before
    cli("apply", target, plan_file, result_file)
    assert load_project(result_file).datasets == p.datasets
    assert load_project(result_file).figure.xlabel == "Time (s)"
    cli("export", result_file, tmp_path / "exports", "--dpi", "100")
