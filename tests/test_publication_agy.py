import pytest
from sps.model import Project, Dataset, Series, FigureSpec, GraphPage, GraphLayer, from_dict
from sps.commands import Session, run_operations
from sps.publication import operation, framed_sides, effective_sides, PROFILES


def make_synthetic_dataset(ds_id="ds_syn_1", name="SyntheticSeries"):
    return Dataset(
        id=ds_id,
        name=name,
        columns={
            "x": [0.0, 1.0, 2.0, 3.0, 4.0],
            "y": [1.5, 3.2, 4.8, 6.1, 8.5],
        },
    )


def test_schema_defaults_and_roundtrip_preservation():
    """Verify legacy schema /1 defaults, effective_sides resolution, and exact roundtrip."""
    ds = make_synthetic_dataset("ds_rt", "RoundtripData")
    s = Series("s_rt", "ds_rt", "x", "y")
    fig = FigureSpec(
        series=[s],
        xlabel="Time (s)",
        ylabel="Voltage (V)",
        xlim=[0.0, 5.0],
        ylim=[0.0, 10.0],
        box=False,
    )
    proj = Project("RoundtripProject", datasets=[ds], figure=fig)
    proj.validate()

    # Legacy schema /1 field defaults preservation
    assert fig.axis_sides is None
    assert fig.layout_mode in (None, "source")
    assert getattr(fig, "label_wrap", False) is False

    # effective_sides fallback when axis_sides is None
    eff_unboxed = effective_sides(FigureSpec(box=False))
    assert eff_unboxed["bottom"]["spine"] is True
    assert eff_unboxed["left"]["spine"] is True
    assert eff_unboxed["top"]["spine"] is False
    assert eff_unboxed["right"]["spine"] is False

    eff_boxed = effective_sides(FigureSpec(box=True))
    assert eff_boxed["bottom"]["spine"] is True
    assert eff_boxed["top"]["spine"] is True
    assert eff_boxed["left"]["spine"] is True
    assert eff_boxed["right"]["spine"] is True

    # Roundtrip serialization preserving fingerprint and coordinate limits
    dumped = proj.to_dict()
    restored = from_dict(dumped)
    restored.validate()
    assert restored.fingerprint() == proj.fingerprint()
    assert restored.figure.xlim == [0.0, 5.0]
    assert restored.figure.ylim == [0.0, 10.0]


def test_single_layer_normalize_publication_data_untouched():
    """Verify single-layer normalization updates typography and framed axes while data and limits remain unchanged."""
    ds = make_synthetic_dataset("ds_norm", "NormData")
    s = Series("s_norm", "ds_norm", "x", "y")
    fig = FigureSpec(
        series=[s],
        xlabel="Energy (eV)",
        ylabel="Photocurrent (nA)",
        xlim=[0.0, 5.0],
        ylim=[0.0, 10.0],
        box=False,
    )
    proj = Project("SingleLayerNormalize", datasets=[ds], figure=fig)
    initial_fp = proj.fingerprint()

    op = operation(profile="nature", size="single", scope="all", font="DejaVu Sans")
    session = Session(proj)
    session.execute([op])

    mod_proj = session.project
    mod_fig = mod_proj.figure

    # Typography and styling updated to publication standard
    assert mod_fig.font == "DejaVu Sans"
    assert mod_fig.axis_width == 0.8
    assert mod_fig.label_wrap is True
    assert mod_fig.layout_mode == "auto"
    assert mod_fig.axis_sides == framed_sides()

    # Numeric data, limits, series identity, and curve properties remain strictly untouched
    assert mod_proj.datasets[0].columns["x"] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert mod_proj.datasets[0].columns["y"] == [1.5, 3.2, 4.8, 6.1, 8.5]
    assert mod_fig.xlim == [0.0, 5.0]
    assert mod_fig.ylim == [0.0, 10.0]
    assert mod_fig.series[0].id == "s_norm"
    assert mod_fig.series[0].dataset == "ds_norm"
    assert mod_proj.fingerprint() != initial_fp


def test_multi_layer_preserves_source_geometry_and_sides():
    """Verify multi-layer figures retain source layout and custom axis configurations without forced auto-framing."""
    ds1 = make_synthetic_dataset("ds_ml1", "MLData1")
    ds2 = make_synthetic_dataset("ds_ml2", "MLData2")
    s1 = Series("s_ml1", "ds_ml1", "x", "y")
    s2 = Series("s_ml2", "ds_ml2", "x", "y")

    fig_main = FigureSpec(
        series=[s1],
        xlabel="Wavelength (nm)",
        ylabel="Absorption (OD)",
        xlim=[0.0, 5.0],
        ylim=[0.0, 10.0],
        box=False,
    )
    custom_sides = {
        "bottom": {"spine": False, "ticks": False, "labels": False},
        "top": {"spine": False, "ticks": False, "labels": False},
        "left": {"spine": False, "ticks": False, "labels": False},
        "right": {"spine": True, "ticks": True, "labels": True},
    }
    fig_right = FigureSpec(
        series=[s2],
        xlabel="",
        ylabel="Transmission (%)",
        xlim=[0.0, 5.0],
        ylim=[0.0, 100.0],
        axis_sides=custom_sides,
        layout_mode="source",
    )

    layer1 = GraphLayer("layer_p1_l1", "MainLayer", fig_main)
    layer2 = GraphLayer("layer_p1_l2", "SecondaryRightAxis", fig_right)
    page = GraphPage("page_ml_1", "MultiLayerPage", [layer1, layer2])
    proj = Project("MultiLayerProject", datasets=[ds1, ds2], pages=[page])
    proj.validate()

    op = operation(profile="communications_materials", size="single", scope="all", font="DejaVu Sans")
    session = Session(proj)
    session.execute([op])

    mod_proj = session.project
    mod_page = mod_proj.pages[0]
    mod_l1 = mod_page.layers[0]
    mod_l2 = mod_page.layers[1]

    # Source layout and right-axis sides preserved on multi-layer
    assert mod_l2.figure.layout_mode == "source"
    assert mod_l2.figure.axis_sides == custom_sides
    # Font updated across layers
    assert mod_l1.figure.font == "DejaVu Sans"
    assert mod_l2.figure.font == "DejaVu Sans"
    # Data and limits preserved
    assert mod_l2.figure.ylim == [0.0, 100.0]
    assert mod_proj.datasets[1].columns["y"] == [1.5, 3.2, 4.8, 6.1, 8.5]

    # Multi-layer layout emits an actionable review issue instead of destroying geometry
    issues = getattr(mod_proj, "issues", None) or getattr(session, "issues", None) or getattr(mod_page, "issues", None)
    assert issues is not None


def test_session_clone_undo_and_context_restoration():
    """Verify session clone isolation, undo semantics, and context restoration."""
    ds = make_synthetic_dataset("ds_undo", "UndoData")
    s = Series("s_undo", "ds_undo", "x", "y")
    fig = FigureSpec(series=[s], xlabel="T (K)", ylabel="Resistance (Ohm)", xlim=[0.0, 5.0], ylim=[0.0, 10.0])
    page = GraphPage("page_undo_1", "UndoPage", [GraphLayer("layer_undo_1", "UndoLayer", fig)])
    proj = Project("UndoProject", datasets=[ds], pages=[page])
    proj.select_context(0, 0)

    orig_fp = proj.fingerprint()
    orig_context = proj.context

    session = Session(proj)
    assert session.project.fingerprint() == orig_fp

    op = operation(profile="elsevier", size="single", scope="page", font="DejaVu Sans")
    session.execute([op])

    # Project instance is replaced with an independent clone
    assert session.project is not proj
    assert session.project.fingerprint() != orig_fp

    # Undo restores state and context
    success = session.undo()
    assert success is True
    assert session.project.datasets == proj.datasets
    assert session.project.figure == proj.figure
    assert session.project.context == orig_context


def test_preview_and_apply_review_tamper_rejection():
    """Verify session preview generates sealed dict and apply_review rejects tampered reviews."""
    ds = make_synthetic_dataset("ds_prev", "PreviewData")
    s = Series("s_prev", "ds_prev", "x", "y")
    fig = FigureSpec(series=[s], xlabel="Frequency (Hz)", ylabel="Power (dBm)", xlim=[0.0, 5.0], ylim=[0.0, 10.0])
    proj = Project("PreviewProject", datasets=[ds], figure=fig)

    session = Session(proj)
    op = operation(profile="nano_letters", size="single", scope="all", font="DejaVu Sans")
    sealed_review = session.preview([op])
    assert isinstance(sealed_review, dict)

    tampered_review = dict(sealed_review, tampered_payload=True)
    with pytest.raises(ValueError):
        session.apply_review(tampered_review)


def test_strict_axis_sides_validation_and_contract():
    """Verify strict validation of axis_sides dictionaries and framed_sides structure."""
    framed = framed_sides()
    for side in ("bottom", "top", "left", "right"):
        assert side in framed
        assert framed[side]["spine"] is True
    assert framed["bottom"]["ticks"] is True
    assert framed["bottom"]["labels"] is True
    assert framed["left"]["ticks"] is True
    assert framed["left"]["labels"] is True
    assert framed["top"]["ticks"] is False
    assert framed["top"]["labels"] is False
    assert framed["right"]["ticks"] is False
    assert framed["right"]["labels"] is False

    # Incomplete specification (missing 'labels') fails validation
    invalid_sides = {
        "bottom": {"spine": True, "ticks": True},
        "top": {"spine": True, "ticks": False, "labels": False},
        "left": {"spine": True, "ticks": True, "labels": True},
        "right": {"spine": True, "ticks": False, "labels": False},
    }
    ds = make_synthetic_dataset("ds_val", "ValidationData")
    s = Series("s_val", "ds_val", "x", "y")
    fig_invalid = FigureSpec(series=[s], xlabel="X", ylabel="Y", axis_sides=invalid_sides)
    proj_invalid = Project("InvalidAxisSidesProject", datasets=[ds], figure=fig_invalid)

    with pytest.raises((ValueError, TypeError)):
        proj_invalid.validate()

    # effective_sides with explicit mapping returns the mapping intact
    valid_sides = {
        "bottom": {"spine": True, "ticks": True, "labels": True},
        "top": {"spine": False, "ticks": False, "labels": False},
        "left": {"spine": True, "ticks": True, "labels": True},
        "right": {"spine": False, "ticks": False, "labels": False},
    }
    resolved = effective_sides(FigureSpec(axis_sides=valid_sides, box=True))
    assert resolved == valid_sides
