"""Apple-style shell acceptance: appearance, ⌘K palette, zoom, sidebar, sheets.

Synthetic documents only; no service requests and no writes outside tmp_path.
"""
import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from sps import theme
from sps.command_palette import Command, CommandPalette, ShortcutsSheet
from sps.gui import MainWindow
from sps.model import Project, demo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    w = MainWindow(demo(), library_dir=tmp_path / "library")
    w.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    w.resize(1510, 960)
    w.show()
    app.processEvents()
    yield w
    w.saved_hash = w.project.fingerprint()
    theme.apply_theme(app, "light")
    w.close()


def test_stylesheet_is_complete_in_both_appearances():
    for mode in ("light", "dark"):
        css = theme.stylesheet(mode)
        assert "$" not in css, "unresolved template placeholder"
        assert theme.tokens(mode)["accent"] in css
        assert "font-family" in css
        assert "QFrame#segmented" in css
    assert theme.stylesheet("light") != theme.stylesheet("dark")
    assert theme.tokens("dark")["window"] != theme.tokens("light")["window"]


def test_appearance_switch_updates_palette_and_icons(window, app):
    w = window
    before = w.appearance
    w.set_appearance("dark")
    app.processEvents()
    assert w.appearance == "dark"
    assert app.palette().color(QPalette.ColorRole.Window) == QColor(theme.tokens("dark")["window"])
    assert theme.tokens("dark")["window"] in app.styleSheet()
    assert w.appearance_button.toolTip().startswith("切换到浅色")
    assert w.settings.value("appearance") == "dark"
    w.toggle_appearance()
    app.processEvents()
    assert w.appearance == "light"
    w.set_appearance("auto")
    assert w.appearance in ("light", "dark")
    assert w.settings.value("appearance") == "auto"
    assert before in ("light", "dark")


def test_command_palette_ranks_titles_and_runs_the_selection(window, app):
    w = window
    calls = []
    commands = [
        Command("导出与校验", lambda: calls.append("export"), "PNG / SVG", "⌘3", "export", "导出", "工作区"),
        Command("切换外观", lambda: calls.append("appearance"), "", "", "moon", "主题", "视图"),
        Command("新建工程", lambda: calls.append("new"), "", "⌘N", "new", "文件", "文件"),
    ]
    palette = CommandPalette(commands, w)
    palette.query.setText("导出")
    app.processEvents()
    assert palette.list.count() == 1
    palette.query.setText("外观")
    app.processEvents()
    assert palette.list.count() == 1
    item = palette.list.item(0)
    palette._activate(item)
    assert calls == ["appearance"]
    assert palette.result() == CommandPalette.DialogCode.Accepted


def test_command_registry_covers_workspaces_and_file_actions(window):
    w = window
    commands = w._commands()
    titles = [c.title for c in commands]
    assert len(commands) >= 20
    for title in ("新建工程", "保存工程", "撤销", "命令面板", "键盘快捷键", "折叠侧栏"):
        assert title in titles
    for title in ("图形编辑", "模板库", "导出校验", "风格审查", "Origin 样式", "AI 助手", "数据与 Office"):
        assert title in titles
    assert all(callable(c.run) for c in commands)
    before = w.project.fingerprint()
    next(c for c in commands if c.title == "折叠侧栏").run()
    next(c for c in commands if c.title == "折叠侧栏").run()
    assert w.project.fingerprint() == before


def test_command_palette_finds_project_objects(window, app):
    w = window
    w.workspaces.setCurrentIndex(w.template_index)
    commands = w._commands()
    series = w.project.figure.series[0]
    entry = next(c for c in commands if c.title == series.label and c.group == "当前工程")
    entry.run()
    app.processEvents()
    assert w.workspaces.currentIndex() == w.editor_index
    assert w.active_id == series.id
    dataset = w.project.datasets[0]
    next(c for c in commands if c.title == dataset.name and c.group == "当前工程").run()
    app.processEvents()
    assert w.dataset_id == dataset.id


def test_sidebar_collapse_keeps_state_and_syncs_controls(window, app):
    w = window
    before = w.project.fingerprint()
    assert w.project_sidebar.isVisible()
    w.sidebar_button.setChecked(False)
    app.processEvents()
    assert not w.project_sidebar.isVisible()
    assert w.sidebar_action.isChecked()
    w.sidebar_action.trigger()
    app.processEvents()
    assert w.project_sidebar.isVisible()
    assert w.sidebar_button.isChecked()
    assert w.project.fingerprint() == before


def test_zoom_changes_only_the_view(window, app):
    w = window
    before = w.project.fingerprint()
    fitted = w.canvas.size()
    w.set_zoom(1.5)
    app.processEvents()
    zoomed = w.canvas.size()
    assert zoomed.width() > fitted.width()
    assert "150%" in w.page_info.text()
    assert w.zoom_buttons[1.5].isChecked()
    w.set_zoom("fit")
    app.processEvents()
    assert w.canvas.size().width() == fitted.width()
    assert "适应窗口" in w.page_info.text()
    assert w.project.fingerprint() == before


def test_shortcuts_sheet_lists_the_new_commands(window, app):
    w = window
    sheet = ShortcutsSheet(w)
    try:
        assert sheet.minimumWidth() >= 820
        text = " ".join(name for _, rows in sheet.GROUPS for name, _ in rows)
        for expected in ("命令面板", "折叠侧栏", "快捷键", "导出与校验"):
            assert expected in text
        sheet.show()
        app.processEvents()
        assert sheet.isVisible()
    finally:
        sheet.close()


def test_scroll_surfaces_skip_the_canvas_viewport(window):
    w = window
    from PySide6.QtWidgets import QScrollArea
    for area in w.findChildren(QScrollArea):
        if area.property("no_surface"):
            assert area.objectName() == "canvas_scroll"
            continue
        if area.widget():
            assert area.widget().objectName() == "scroll_surface"
