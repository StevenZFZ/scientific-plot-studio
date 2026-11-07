from dataclasses import asdict
import copy
import pytest

from sps.model import demo, Annotation
from sps.commands import Session, run_operations, style_from_project
from sps.review import review_rows, selected_operations


def test_selective_style_only_applies_selected_property():
    p = demo()
    style = style_from_project(p)
    style["figure"].update(font_size=12, grid=True)
    style["series"][0]["color"] = "#112233"
    operations = [{"op": "apply_style", "style": style}]
    rows = review_rows(p, operations)
    before = p.to_dict()
    take = ["字号" in row["label"] for row in rows]
    filtered = selected_operations(rows, take)
    session = Session(p)
    session.apply_review(session.preview(filtered))
    assert session.project.figure.font_size == 12
    assert not session.project.figure.grid
    assert session.project.figure.series[0].color == before["figure"]["series"][0]["color"]
    assert session.project.datasets == p.datasets
    assert len(rows) == 3


def test_all_selectable_changes_reproduce_original_plan_semantics():
    p = demo()
    ops = [{"op": "set_figure", "changes": {"grid": True, "width_mm": 150}},
           {"op": "set_series", "ids": ["series_ref", "series_mod"], "changes": {"width": 2.5, "marker": "o"}}]
    rows = review_rows(p, ops)
    assert run_operations(p, selected_operations(rows, [True] * len(rows))).to_dict() == run_operations(p, ops).to_dict()
    assert selected_operations(rows, [False] * len(rows)) == []


def test_data_and_structural_changes_remain_single_atomic_transaction():
    p = demo()
    ops = [{"op": "set_figure", "changes": {"grid": True}},
           {"op": "set_cell", "dataset": "data_demo", "column": "Reference", "row": 0, "value": .5}]
    rows = review_rows(p, ops)
    assert len(rows) == 1
    assert "完整事务" in rows[0]["label"]
    assert selected_operations(rows, [True]) == ops
    ops[0]["changes"]["grid"] = False
    assert rows[0]["operations"][0]["changes"]["grid"] is True


def test_large_style_plan_does_not_overflow_operation_limit():
    p = demo()
    for i in range(101):
        s = copy.deepcopy(p.figure.series[0])
        s.id = f"copy{i}"
        p.figure.series.append(s)
    ops = [{"op": "set_series", "ids": [s.id for s in p.figure.series], "changes": {"width": 3}}]
    rows = review_rows(p, ops)
    assert len(rows) == 1
    assert run_operations(p, selected_operations(rows, [True])).figure.series[-1].width == 3


def test_partial_dependent_changes_fail_validation_instead_of_silent_fix():
    p = demo()
    ops = [{"op": "set_series", "ids": ["series_ref"], "changes": {"kind": "errorbar", "y_error": "Error"}}]
    rows = review_rows(p, ops)
    filtered = selected_operations(rows, [row["after"] == "errorbar" for row in rows])
    with pytest.raises(ValueError, match="误差棒"):
        run_operations(p, filtered)
    assert p.figure.series[0].kind == "line"
