import hashlib
import io
import json
import uuid
import zipfile
import pytest

from sps.model import demo
from sps import figure_object as f


@pytest.fixture(scope="module")
def built_package():
    project = demo()
    package_bytes = f.build(project, revision=1, dpi=150)
    return project, package_bytes


def test_build_unpack_roundtrip_and_manifest_schema(built_package):
    project, package_bytes = built_package
    unpacked = f.unpack(package_bytes)

    assert "project" in unpacked
    assert "manifest" in unpacked
    assert "files" in unpacked
    assert "sha256" in unpacked
    assert unpacked["sha256"] == hashlib.sha256(package_bytes).hexdigest()

    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as zf:
        namelist = sorted(zf.namelist())
    assert namelist == ["manifest.json", "preview.png", "preview.svg", "project.json"]

    manifest = unpacked["manifest"]
    assert manifest.get("schema") == "sps.figure/1"

    parsed_uuid = uuid.UUID(manifest["id"])
    assert str(parsed_uuid) == manifest["id"]

    assert isinstance(manifest["revision"], int)
    assert 1 <= manifest["revision"] <= 1000000

    ctx = manifest["context"]
    assert isinstance(ctx, dict)
    assert isinstance(ctx["page"], int) and ctx["page"] >= 0
    assert isinstance(ctx["layer"], int) and ctx["layer"] >= 0

    assert manifest["width_mm"] > 0
    assert manifest["height_mm"] > 0
    assert manifest["preview_scope"] == "all layers of selected page; complete document retained"
    assert isinstance(manifest["png_pixels"], str) and len(manifest["png_pixels"]) == 64

    files = manifest["files"]
    assert sorted(files.keys()) == ["preview.png", "preview.svg", "project.json"]
    for filename, digest in files.items():
        assert digest == hashlib.sha256(unpacked["files"][filename]).hexdigest()


def test_unpack_rejects_extra_duplicate_entries_and_corrupt_parts(built_package):
    _, package_bytes = built_package

    # Extra unauthorized ZIP entries must trigger validation rejection
    buf_extra = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as src_zf:
        with zipfile.ZipFile(buf_extra, "w") as dst_zf:
            for item in src_zf.infolist():
                dst_zf.writestr(item, src_zf.read(item.filename))
            dst_zf.writestr("unauthorized.txt", b"payload")
    with pytest.raises(ValueError):
        f.unpack(buf_extra.getvalue())

    # Tampered part bytes with mismatching manifest digest must be rejected
    buf_tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as src_zf:
        with zipfile.ZipFile(buf_tampered, "w") as dst_zf:
            for item in src_zf.infolist():
                data = src_zf.read(item.filename)
                if item.filename == "project.json":
                    data = data + b" "
                dst_zf.writestr(item.filename, data)
    with pytest.raises(ValueError):
        f.unpack(buf_tampered.getvalue())

    # Duplicate entries in the ZIP directory must be rejected
    buf_dup = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as src_zf:
        with zipfile.ZipFile(buf_dup, "w") as dst_zf:
            for item in src_zf.infolist():
                dst_zf.writestr(item.filename, src_zf.read(item.filename))
            dst_zf.writestr("preview.png", b"duplicate")
    with pytest.raises(ValueError):
        f.unpack(buf_dup.getvalue())


def test_unpack_rejects_tampered_manifest_and_invalid_context(built_package):
    _, package_bytes = built_package
    with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as src_zf:
        entries = {item.filename: src_zf.read(item.filename) for item in src_zf.infolist()}

    manifest_dict = json.loads(entries["manifest.json"].decode("utf-8"))

    # Non-canonical UUID in manifest.id must fail
    bad_id = dict(manifest_dict, id="non-uuid-identifier")
    buf_bad_id = io.BytesIO()
    with zipfile.ZipFile(buf_bad_id, "w") as dst_zf:
        for fname, data in entries.items():
            dst_zf.writestr(fname, json.dumps(bad_id).encode("utf-8") if fname == "manifest.json" else data)
    with pytest.raises(ValueError):
        f.unpack(buf_bad_id.getvalue())

    # Revision out of valid bounds (1..1000000) must fail
    bad_rev = dict(manifest_dict, revision=0)
    buf_bad_rev = io.BytesIO()
    with zipfile.ZipFile(buf_bad_rev, "w") as dst_zf:
        for fname, data in entries.items():
            dst_zf.writestr(fname, json.dumps(bad_rev).encode("utf-8") if fname == "manifest.json" else data)
    with pytest.raises(ValueError):
        f.unpack(buf_bad_rev.getvalue())

    # Negative layer/page context indices must fail
    bad_ctx = dict(manifest_dict, context={"page": -1, "layer": 0})
    buf_bad_ctx = io.BytesIO()
    with zipfile.ZipFile(buf_bad_ctx, "w") as dst_zf:
        for fname, data in entries.items():
            dst_zf.writestr(fname, json.dumps(bad_ctx).encode("utf-8") if fname == "manifest.json" else data)
    with pytest.raises(ValueError):
        f.unpack(buf_bad_ctx.getvalue())


def test_save_optimistic_concurrency_and_revision_increment(tmp_path):
    project = demo()
    target_path = tmp_path / "figure.spsfig"

    res1 = f.save(project, str(target_path), revision=1)
    initial_sha = res1["sha256"]
    figure_id = res1["manifest"]["id"]
    assert res1["manifest"]["revision"] == 1

    project.figure.title = "Modified Title for Concurrency Test"

    # Mismatched expected_sha must abort write and retain existing payload
    with pytest.raises(ValueError):
        f.save(project, str(target_path), expected_sha="0" * 64)

    existing = f.load(str(target_path))
    assert existing["sha256"] == initial_sha
    assert existing["manifest"]["revision"] == 1

    # Correct expected_sha proceeds with atomic revision bump and identical identity
    res2 = f.save(project, str(target_path), expected_sha=initial_sha)
    assert res2["sha256"] != initial_sha
    assert res2["manifest"]["id"] == figure_id
    assert res2["manifest"]["revision"] == 2

    reloaded = f.load(str(target_path))
    assert reloaded["manifest"]["revision"] == 2
    assert reloaded["manifest"]["id"] == figure_id
    assert reloaded["project"].figure.title == "Modified Title for Concurrency Test"


def test_png_carrier_embedding_rejection_and_pixel_tamper_detection(built_package):
    _, package_bytes = built_package
    carrier_png = f.png_carrier(package_bytes)
    assert f.PNG_TAG in carrier_png

    extracted = f.from_png(carrier_png)
    assert "project" in extracted
    assert "manifest" in extracted
    assert extracted["manifest"]["schema"] == "sps.figure/1"
    assert extracted["package"] == package_bytes

    # Ordinary PNG without payload carrier chunk must be rejected
    unpacked = f.unpack(package_bytes)
    plain_png = unpacked["files"]["preview.png"]
    with pytest.raises(ValueError):
        f.from_png(plain_png)

    # A damaged PNG header with payload intact must be rejected (pixel edit is tested independently)
    tag_pos = carrier_png.index(f.PNG_TAG)
    tampered_bytes = bytearray(carrier_png)
    tampered_bytes[min(16, tag_pos - 4)] ^= 0xFF
    with pytest.raises(ValueError):
        f.from_png(bytes(tampered_bytes))


def test_svg_carrier_embedding_rejection_and_path_tamper_detection(built_package):
    _, package_bytes = built_package
    carrier_svg = f.svg_carrier(package_bytes)

    extracted = f.from_svg(carrier_svg)
    assert "project" in extracted
    assert "manifest" in extracted
    assert extracted["package"] == package_bytes

    # Ordinary SVG without metadata must be rejected
    ordinary_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><circle cx="25" cy="25" r="20"/></svg>'
    with pytest.raises(ValueError):
        f.from_svg(ordinary_svg)

    # Mutating SVG path or structure while retaining metadata must be rejected
    if b"<path" in carrier_svg:
        tampered_svg = carrier_svg.replace(b"<path", b'<path d="M0,0 L10,10"', 1)
    else:
        tampered_svg = carrier_svg.replace(b"</svg>", b'<rect x="0" y="0" width="10" height="10"/></svg>', 1)
    with pytest.raises(ValueError):
        f.from_svg(tampered_svg)
