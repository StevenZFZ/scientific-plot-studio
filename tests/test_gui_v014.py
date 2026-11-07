"""0.14 acceptance: journal templates, Arial/思源黑体 defaults, flat hairlines,
and removal of unreachable UI.

Synthetic documents only; no network and no writes outside tmp_path.
"""
import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox

from sps import templates, theme
from sps.gui import MainWindow
from sps.model import FigureSpec, demo
from sps.render import preflight
from sps.template_ui import TemplateLibraryPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    w = MainWindow(demo(), library_dir=tmp_path / "library")
    w.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w.set_appearance("light")
    w.resize(1510, 960)
    w.show()
    app.processEvents()
    yield w
    w.saved_hash = w.project.fingerprint()
    theme.apply_theme(app, "light")
    w.close()


def test_journal_templates_cover_publishers_with_published_widths():
    builtins = templates.builtin_templates()
    assert len(builtins) >= 10
    by_id = {t.id: t for t in builtins}
    expected = {
        "builtin_nature_single": 89,
        "builtin_nature_double": 183,
        "builtin_science_single": 55,
        "builtin_cell_double": 174,
        "builtin_acs_single": 82.5,
        "builtin_ieee_double": 181,
        "builtin_elsevier_double": 190,
    }
    for ident, width in expected.items():
        template = by_id[ident]
        assert template.figure["width_mm"] == pytest.approx(width)
        assert template.figure["font"] == "Arial"
        assert template.description.strip(), "每个模板必须说明官方依据与 SPS 选择"
        assert "SPS" in template.description
    # The third slot must stay the error-bar template: existing workflows and
    # tests address builtin_templates()[2] directly.
    assert by_id["builtin_nature_errorbar"].slots[0].properties["kind"] == "errorbar"
    assert builtins[2].id == "builtin_nature_errorbar"


def test_utility_templates_are_not_color_only():
    by_id = {t.id: t for t in templates.builtin_templates()}
    gray = by_id["builtin_grayscale"]
    markers = {slot.properties["marker"] for slot in gray.slots}
    styles = {slot.properties["line_style"] for slot in gray.slots}
    assert len(markers) >= 3 and len(styles) >= 3, "灰度模板必须靠点形与线型区分"
    blind = by_id["builtin_colorblind"]
    colors = {slot.properties["color"] for slot in blind.slots}
    assert "#0072B2" in colors and "#D55E00" in colors
    slides = by_id["builtin_slides"]
    assert slides.figure["font_size"] >= 12 and slides.figure["grid"] is True


def test_every_template_previews_without_overflow():
    for template in templates.builtin_templates():
        project = templates.preview_project(template)
        assert all(d.synthetic for d in project.datasets)
        assert len(project.figure.series) == len(template.slots)
        preflight(project, 100)


def test_font_defaults_are_arial_with_source_han_fallback():
    assert FigureSpec().font == "Arial"
    stack = theme.FONT_STACK
    assert stack.index('"Arial"') < stack.index('"Source Han Sans SC"') < stack.index('"PingFang SC"')
    for mode in ("light", "dark"):
        css = theme.stylesheet(mode)
        assert "Arial" in css and "Source Han Sans SC" in css


def test_font_field_is_a_selector_not_free_text(window):
    w = window
    field = w.fig_fields["font"]
    assert isinstance(field, QComboBox)
    assert field.findData("Arial") >= 0
    assert field.minimumContentsLength() == 12
    # A long font list must not widen the inspector beyond its column.
    inspector = w.right_stack.widget(0).widget()
    assert inspector.minimumSizeHint().width() <= w.right_stack.width()
    assert w.project.figure.font == "Arial"
    field.setCurrentIndex(field.findData("Arial"))
    w.apply_figure()
    assert w.project.figure.font == "Arial"


def test_missing_project_font_is_shown_explicitly(window):
    w = window
    w.project.figure.font = "Not Installed Family"
    w.refresh_inspector()
    field = w.fig_fields["font"]
    assert field.findData("Not Installed Family") == 0
    assert "未安装" in field.itemText(0)


def test_borders_are_hairlines_where_enclosure_is_meaningless():
    css = theme.stylesheet("light")
    group = css.split("QGroupBox {")[1].split("}")[0]
    assert "border-top: 1px solid" in group
    assert "border-radius: 0" in group
    table = css.split("QTableWidget {")[1].split("}")[0]
    assert "border: 1px solid" in table and "border-radius: 0" in table
    preview = css.split("QLabel#preview_card {")[1].split("}")[0]
    assert "border-radius: 0" in preview


def test_unreachable_ui_is_gone(window):
    w = window
    assert w.right_stack.count() == 2, "右侧只保留属性与导出两页"
    assert not hasattr(w, "workspace_spacer")
    assert "本地模式" not in w.document_info.text()
    assert "Arial" in w.document_info.text()
    assert not hasattr(w.template_panel, "originRequested"), "无实现的 Origin 模板入口已移除"


def test_template_panel_lists_journal_metadata(window):
    panel = window.template_panel
    assert panel.list.count() == len(templates.builtin_templates())
    text = panel.list.item(0).text()
    assert "Nature" in text and "Arial" in text and "mm" in text


def test_empty_export_preview_is_flat_not_checkerboard(window, app):
    from PySide6.QtGui import QColor, QPalette
    window.workspaces.setCurrentIndex(window.export_index)
    app.processEvents()
    preview = window.export_preview
    image = preview.grab().toImage()
    # Sample away from the centred placeholder text and the 1 px hairline.
    colour = image.pixelColor(12, 12)
    assert colour == window.palette().color(QPalette.ColorRole.Window)
    assert colour != QColor("#e3e8ec")
