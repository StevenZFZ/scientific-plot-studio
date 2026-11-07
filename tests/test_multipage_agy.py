import copy
import pytest
from sps.model import Project, Dataset, Series, FigureSpec, GraphPage, GraphLayer, from_dict
from sps.commands import Session


@pytest.fixture
def synthetic_multipage_project():
    ds = Dataset(
        id="ds_shared_phys_01",
        name="SharedTable",
        columns={"x": [1.0, 2.0, 3.0], "y": [10.0, 20.0, 30.0]}
    )
    s1 = Series(id="crv_g10_ly1_001", dataset="ds_shared_phys_01", x="x", y="y")
    s2 = Series(id="crv_g10_ly2_002", dataset="ds_shared_phys_01", x="x", y="y")
    s3 = Series(id="crv_doufu_ly1_003", dataset="ds_shared_phys_01", x="x", y="y")

    layer_g10_1 = GraphLayer(
        id="layer_g10_main",
        name="Layer1",
        figure=FigureSpec(title="Graph10 Primary", series=[s1]),
        rect=[0.0, 0.0, 1.0, 1.0],
        issues=[]
    )
    layer_g10_2 = GraphLayer(
        id="layer_g10_inset",
        name="Layer2",
        figure=FigureSpec(title="Graph10 Inset", series=[s2]),
        rect=[0.55, 0.55, 0.4, 0.4],
        issues=[]
    )
    page_g10 = GraphPage(
        id="page_g10_01",
        name="Graph10",
        layers=[layer_g10_1, layer_g10_2],
        source_index=0,
        issues=[]
    )

    layer_doufu = GraphLayer(
        id="layer_df_main",
        name="Layer1",
        figure=FigureSpec(title="豆腐图 Main", series=[s3]),
        rect=[0.0, 0.0, 1.0, 1.0],
        issues=["style_warning:custom_hatch_degraded"]
    )
    page_doufu = GraphPage(
        id="page_doufu_02",
        name="豆腐图",
        layers=[layer_doufu],
        source_index=1,
        issues=[]
    )

    return Project(
        name="SyntheticProject2",
        datasets=[ds],
        pages=[page_g10, page_doufu]
    )


def test_multipage_schema_and_navigation_invariance(synthetic_multipage_project):
    p = synthetic_multipage_project
    d_initial = p.to_dict()
    fp_initial = p.fingerprint()
    assert d_initial.get("schema") == "sps.project/2"
    assert p.context == (0, 0)
    assert p.figure.title == "Graph10 Primary"

    p.select_context(0, 1)
    assert p.context == (0, 1)
    assert p.figure.title == "Graph10 Inset"

    p.select_context(1, 0)
    assert p.context == (1, 0)
    assert p.figure.title == "豆腐图 Main"

    # View navigation must strictly preserve fingerprint and serialization
    assert p.fingerprint() == fp_initial
    assert p.to_dict() == d_initial


def test_multipage_clone_independence_and_context(synthetic_multipage_project):
    p = synthetic_multipage_project
    p.select_context(0, 1)
    cloned = p.clone()

    assert cloned.context == (0, 1)
    assert cloned.figure.title == "Graph10 Inset"

    # Mutating cloned active figure must not alias or affect original
    cloned.figure.title = "Cloned Mutated Inset"
    assert p.figure.title == "Graph10 Inset"
    assert cloned.pages[0].layers[1] is not p.pages[0].layers[1]
    assert cloned.pages[0].layers[1].figure is not p.pages[0].layers[1].figure


def test_session_scoped_edit_preserves_unrelated_pages_and_layers(synthetic_multipage_project):
    p = synthetic_multipage_project
    p.select_context(0, 1)

    # Snapshot unedited layers and pages
    page0_ly0_snapshot = copy.deepcopy(p.pages[0].layers[0].figure.to_dict() if hasattr(p.pages[0].layers[0].figure, "to_dict") else vars(p.pages[0].layers[0].figure))
    page1_snapshot = copy.deepcopy(p.pages[1].to_dict() if hasattr(p.pages[1], "to_dict") else vars(p.pages[1]))

    sess = Session(p)
    sess.execute([{"op": "set_figure", "changes": {"title": "Graph10 Inset Modified"}}])

    p=sess.project
    assert p.figure.title == "Graph10 Inset Modified"
    # Unrelated layer on page 0 and complete page 1 remain byte/dict intact
    curr_p0_ly0 = p.pages[0].layers[0].figure.to_dict() if hasattr(p.pages[0].layers[0].figure, "to_dict") else vars(p.pages[0].layers[0].figure)
    curr_p1 = p.pages[1].to_dict() if hasattr(p.pages[1], "to_dict") else vars(p.pages[1])
    assert curr_p0_ly0 == page0_ly0_snapshot
    assert curr_p1 == page1_snapshot

    # Undo restores original figure and returns edit context
    assert sess.undo()
    p=sess.project
    assert p.context == (0,1)
    assert p.figure.title == "Graph10 Inset"


def test_full_validation_catches_hidden_page_defects(synthetic_multipage_project):
    p = synthetic_multipage_project
    p.select_context(0, 0)
    # Introduce an invalid reference in hidden page 1 layer 0
    p.pages[1].layers[0].figure.series[0].dataset = "missing_ghost_dataset"

    with pytest.raises(ValueError):
        p.validate()


def test_multipage_roundtrip_preserves_all_pages_and_duplicate_names(synthetic_multipage_project):
    p = synthetic_multipage_project
    # Append page with duplicate name 'Graph10' to verify explicit preservation
    dup_layer = GraphLayer(
        id="layer_g10_dup_01",
        name="Layer1",
        figure=FigureSpec(title="Duplicate Graph10", series=[]),
        rect=[0.0, 0.0, 1.0, 1.0],
        issues=[]
    )
    dup_page = GraphPage(id="page_g10_dup_03", name="Graph10", layers=[dup_layer], source_index=2, issues=[])
    p.pages.append(dup_page)

    p.select_context(1, 0)
    saved_dict = p.to_dict()
    restored = from_dict(saved_dict)

    assert restored.context == (0, 0)  # from_dict defaults to first context
    assert len(restored.pages) == 3
    assert [page.name for page in restored.pages] == ["Graph10", "豆腐图", "Graph10"]
    assert restored.pages[0].layers[1].figure.title == "Graph10 Inset"
    assert restored.pages[1].layers[0].issues == ["style_warning:custom_hatch_degraded"]


def test_session_preview_sealed_context_rejection_on_page_switch(synthetic_multipage_project):
    p = synthetic_multipage_project
    p.select_context(0, 0)
    sess = Session(p)

    preview = sess.preview([{"op": "set_figure", "changes": {"title": "Page 0 Target Edit"}}])
    # Switch context before applying sealed review
    p.select_context(1, 0)

    with pytest.raises((ValueError, RuntimeError, KeyError)):
        sess.apply_review(preview)


def test_cross_page_shared_dataset_cell_edit_updates_globally(synthetic_multipage_project):
    p = synthetic_multipage_project
    sess = Session(p)

    sess.execute([{"op": "set_cell", "dataset": "ds_shared_phys_01", "column": "y", "row": 1, "value": 99.0}])

    p=sess.project
    ds = next(d for d in p.datasets if d.id == "ds_shared_phys_01")
    assert ds.columns["y"][1] == 99.0

    # Verify both contexts reference the updated underlying cell
    p.select_context(0, 0)
    target_ds_p0 = next(d for d in p.datasets if d.id == p.figure.series[0].dataset)
    assert target_ds_p0.columns["y"][1] == 99.0

    p.select_context(1, 0)
    target_ds_p1 = next(d for d in p.datasets if d.id == p.figure.series[0].dataset)
    assert target_ds_p1.columns["y"][1] == 99.0
