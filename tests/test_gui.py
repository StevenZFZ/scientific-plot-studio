import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
import pytest

from sps.gui import MainWindow
from sps.model import demo, load
from sps.render import draw
from sps import templates
from sps.gui import CaptureTemplateDialog, TemplateBindingDialog
from PySide6.QtWidgets import QDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(str(args[-1])))
    w = MainWindow(demo(), library_dir=tmp_path / "library")
    w.show()
    app.processEvents()
    yield w, errors
    w.saved_hash = w.project.fingerprint()
    w.close()
    assert not errors


def test_gui_editor_data_edit_undo_save_reopen(window, app, tmp_path):
    w, _ = window
    w.property_tabs.setCurrentIndex(2)
    w.fig_fields["title"].setText("Edited through Qt")
    QTest.mouseClick(w.findChild(type(w.apply_review_button), "apply_figure"), Qt.MouseButton.LeftButton)
    assert w.project.figure.title == "Edited through Qt"
    w.series_fields["width"].setValue(2.2)
    w.apply_series()
    assert w.project.figure.series[0].width == 2.2
    w.data_table.item(0, 1).setText("0.125")
    assert w.project.datasets[0].columns["Reference"][0] == .125
    w.undo()
    assert w.project.datasets[0].columns["Reference"][0] != .125
    w.redo()
    path = tmp_path / "gui.sps.json"
    assert w.save_project(path=path)
    w.replace_project(load(path), path)
    assert w.project.figure.title == "Edited through Qt"
    assert w.project.figure.series[0].width == 2.2
    assert w.project.datasets[0].columns["Reference"][0] == .125


def test_gui_agent_preview_apply_and_invalidation(window, app):
    w, _ = window
    w.workspaces.setCurrentIndex(w.agent_index)
    w.agent_input.setPlainText(json.dumps([{"op": "set_figure", "changes": {"grid": True}}]))
    w.preview_agent()
    assert w.pending_review and w.apply_review_button.isEnabled()
    assert not w.project.figure.grid
    assert not w.after_preview.pixmap().isNull()
    w.apply_agent()
    assert w.project.figure.grid
    assert not w.apply_review_button.isEnabled()
    w.preview_agent()
    w.agent_input.setPlainText("[]")
    assert w.pending_review is None


def test_gui_export_workbench_actual_files(window, app, tmp_path):
    w, _ = window
    w.workspaces.setCurrentIndex(w.export_index)
    w.export_dir.setText(str(tmp_path))
    w.export_dpi.setValue(100)
    w.run_preflight()
    assert not w.export_preview.original.isNull()
    w.do_export()
    assert all((tmp_path / f"figure.{suffix}").exists() for suffix in ("png", "svg", "pdf", "tiff", "export.json"))
    assert "验证通过" in w.export_report.toPlainText()


def test_gui_annotation_and_batch_style(window):
    w, _ = window
    w.add_annotation()
    assert len(w.project.figure.annotations) == 1
    w.annotation_fields["text"].setText("(b)")
    w.apply_annotation()
    assert w.project.figure.annotations[0].text == "(b)"
    w.remove_object()
    assert not w.project.figure.annotations
    w.active_id = "series_ref"
    w.refresh_inspector()
    w.batch_all.setChecked(True)
    w.series_fields["width"].setValue(3)
    w.apply_series()
    assert all(s.width == 3 for s in w.project.figure.series)
    assert w.project.figure.series[0].label == "Reference"
    assert w.project.figure.series[1].label == "Modified"


def test_canvas_buffer_tracks_native_widget_after_repeated_edits_and_resize(window, app):
    w, _ = window
    for width, height in [(1450, 920), (1200, 780), (1550, 960)]:
        w.resize(width, height)
        app.processEvents()
        w.execute([{"op": "set_figure", "changes": {"width_mm": 80}}])
        app.processEvents()
        buffer_width, buffer_height = w.canvas.get_width_height(physical=True)
        assert abs(buffer_width - w.canvas.width() * w.canvas.device_pixel_ratio) <= 1
        assert abs(buffer_height - w.canvas.height() * w.canvas.device_pixel_ratio) <= 1
        assert abs(w.canvas.renderer.width - buffer_width) <= 1
        assert abs(w.canvas.renderer.height - buffer_height) <= 1


def test_editor_toolbar_cannot_bypass_model_or_export_validation(window):
    w, _ = window
    assert set(w.navigation._actions) == {"home", "back", "forward", "pan", "zoom"}


def test_gui_selective_review_changes_preview_and_applies_only_checked(window, app):
    w, _ = window
    w.agent_input.setPlainText(json.dumps([{"op": "set_figure", "changes": {"grid": True, "font_size": 12}}]))
    w.preview_agent()
    assert w.review_table.rowCount() == 2
    grid_row = next(i for i, row in enumerate(w.review_items) if "网格" in row["label"])
    w.review_table.item(grid_row, 0).setCheckState(Qt.CheckState.Unchecked)
    assert len(w.pending_review["changes"]) == 1
    assert w.pending_review["changes"][0]["path"] == "/figure/font_size"
    w.apply_agent()
    assert w.project.figure.font_size == 12 and not w.project.figure.grid
    w.undo()
    assert w.project.figure.font_size == 10


def test_gui_empty_or_invalid_partial_selection_cannot_apply(window):
    w, _ = window
    w.agent_input.setPlainText(json.dumps([{"op": "set_series", "ids": ["series_ref"],
                                          "changes": {"kind": "errorbar", "y_error": "Error"}}]))
    w.preview_agent()
    error_row = next(i for i, row in enumerate(w.review_items) if "误差列" in row["label"])
    w.review_table.item(error_row, 0).setCheckState(Qt.CheckState.Unchecked)
    assert w.pending_review is None and not w.apply_review_button.isEnabled()
    assert "误差棒" in w.review_summary.text()
    for i in range(w.review_table.rowCount()):
        w.review_table.item(i, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not w.apply_review_button.isEnabled()


def test_gui_export_real_svg_preview_background_and_stale_settings(window, tmp_path):
    w, _ = window
    w.export_dir.setText(str(tmp_path))
    w.export_dpi.setValue(100)
    w.do_export()
    assert not w.svg_preview.original.isNull()
    assert w.svg_preview.original.toImage().pixelColor(0, 0).alpha() == 0
    assert json.loads((tmp_path / "figure.preview.json").read_text())["passed"]
    assert all(w.export_checks.item(i, 1).text() == "通过" for i in range(4))
    assert w.export_checks.item(4, 1).text() == "未验证"
    previous = w.last_export
    w.preview_background.setCurrentIndex(2)
    assert w.export_preview.background_mode == "black"
    assert w.svg_preview.background_mode == "black"
    assert w.last_export is previous and w.transparent.isChecked()
    w.export_dpi.setValue(150)
    assert w.last_export is None
    assert w.svg_preview.original.isNull()
    assert all(w.export_checks.item(i, 1).text() == "待导出" for i in range(4))


def test_gui_tree_visibility_and_property_routing(window, app):
    w, _ = window
    figure = w.tree.topLevelItem(0).child(0)
    first = figure.child(1)
    first.setCheckState(0, Qt.CheckState.Unchecked)
    app.processEvents()
    assert not w.project.figure.series[0].visible
    assert w.project.figure.series[1].visible
    w.undo()
    assert w.project.figure.series[0].visible
    figure = w.tree.topLevelItem(0).child(0)
    w.tree.setCurrentItem(figure.child(0))
    assert w.property_tabs.currentIndex() == 1
    w.tree.setCurrentItem(figure)
    assert w.property_tabs.currentIndex() == 2
    w.tree.setCurrentItem(figure.child(1))
    assert w.property_tabs.currentIndex() == 0
    w.series_fields["color"].setText("#112233")
    w.apply_series()
    assert w.project.figure.series[0].color == "#112233"


def test_svg_reader_does_not_silently_accept_warnings(window, tmp_path):
    from sps.widgets import svg_pixmap
    from sps.render import normalize_svg_empty_paths
    file = tmp_path / "empty.svg"
    file.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><path id="space"/></defs><use href="#space"/></svg>')
    with pytest.raises(ValueError, match="阅读器"):
        svg_pixmap(file)
    assert normalize_svg_empty_paths(file) == 1
    assert not svg_pixmap(file).isNull()


def test_export_canvas_shortcut_and_background_do_not_change_model(window):
    w, _ = window
    before = w.project.fingerprint()
    w.workspaces.setCurrentIndex(w.export_index)
    assert w.right_stack.currentIndex() == 1
    w.go_to_canvas()
    assert w.right_stack.currentIndex() == 0 and w.property_tabs.currentIndex() == 2
    assert w.project.fingerprint() == before


def test_template_capture_library_persistence_and_portable_export(window, monkeypatch, tmp_path):
    w, _ = window
    before = w.project.fingerprint()
    def capture(dialog):
        dialog.name.setText("Reusable local template")
        dialog.description.setText("Explicit data binding")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(CaptureTemplateDialog, "exec", capture)
    w.capture_native_template()
    assert w.project.fingerprint() == before
    assert w.workspaces.currentIndex() == w.template_index
    selected = w.template_panel.selected_template()
    assert selected.name == "Reusable local template"
    assert selected.source["kind"] == "native"
    assert len(w.template_library.items()) == len(templates.builtin_templates()) + 1
    assert all(d.synthetic for d in w.template_panel.last_preview_project.datasets)
    exported = tmp_path / "portable.sps-template.json"
    w.export_native_template(exported)
    assert templates.load(exported).to_dict() == selected.to_dict()


def test_template_binding_review_apply_undo_keeps_raw_data(window, monkeypatch):
    import copy
    w, _ = window
    before_data = copy.deepcopy(w.project.datasets)
    original_figure = copy.deepcopy(w.project.figure)
    w.template_panel.list.setCurrentRow(1)
    def bind(dialog):
        dialog.labels["title"].setText("New explicitly bound data")
        dialog.labels["x_label"].setText("Wavelength (nm)")
        dialog.labels["y_label"].setText("Intensity (a.u.)")
        dialog.rows[0]["y"].setCurrentText("Modified")
        dialog.rows[1]["y"].setCurrentText("Reference")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(TemplateBindingDialog, "exec", bind)
    w.bind_native_template()
    assert w.workspaces.currentIndex() == w.agent_index
    assert w.project.figure == original_figure
    assert w.pending_review["operations"][0]["op"] == "apply_template"
    assert w.review_table.rowCount() == 1
    w.apply_agent()
    assert w.workspaces.currentIndex() == w.editor_index
    assert w.project.figure.series[0].y == "Modified"
    assert w.project.figure.series[1].y == "Reference"
    assert w.project.figure.title == "New explicitly bound data"
    assert w.project.datasets == before_data
    w.undo()
    assert w.project.figure == original_figure
    w.redo()
    assert w.project.figure.series[0].y == "Modified"


def test_template_binding_error_column_is_not_guessed(window):
    w, _ = window
    t = templates.builtin_templates()[2]
    dialog = TemplateBindingDialog(w.project, t, w)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "误差列" in dialog.error_message.text()
    dialog.rows[0]["error"].setCurrentText("Error")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_project_search_is_view_only(window):
    w, _ = window
    before = w.project.fingerprint()
    figure = w.tree.topLevelItem(0).child(0)
    w.project_filter.setText("Modified")
    assert figure.child(1).isHidden()
    assert not figure.child(2).isHidden()
    w.project_filter.clear()
    assert not figure.child(1).isHidden()
    assert w.project.fingerprint() == before


def test_visibility_rapid_toggle_coalesces_without_deleting_active_item(window, app):
    w, _ = window
    initial = w.project.fingerprint()
    item = w.tree.topLevelItem(0).child(0).child(1)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    item.setCheckState(0, Qt.CheckState.Checked)
    app.processEvents()
    assert w.project.fingerprint() == initial
    assert w.project.figure.series[0].visible


def test_display_enums_and_opacity_preserve_model_values(window):
    w, _ = window
    w.series_fields["kind"].setCurrentIndex(w.series_fields["kind"].findData("scatter"))
    w.series_fields["alpha"].setValue(65)
    w.apply_series()
    assert w.project.figure.series[0].kind == "scatter"
    assert w.project.figure.series[0].alpha == .65
    assert w.series_fields["kind"].currentText() == "散点"


def test_template_tab_uses_full_workspace_and_returns_to_editor(window, app):
    w, _ = window
    w.workspaces.setCurrentIndex(w.template_index)
    app.processEvents()
    assert w.right_stack.isHidden()
    assert w.workspace_nav.currentRow() == w.template_index
    assert w.bottom_panel.isHidden()
    w.workspaces.setCurrentIndex(w.editor_index)
    app.processEvents()
    assert not w.bottom_panel.isHidden()
    ratio = w.canvas.width() / w.canvas.height()
    expected = w.project.figure.width_mm / w.project.figure.height_mm
    assert abs(ratio - expected) < .02


def test_gui_origin_analysis_transfer_preserves_data_and_selects_reference(window):
    from test_origin_workflow import analysis_fixture
    w,_=window;before=w.project.clone()
    w.origin_panel.set_report(analysis_fixture())
    assert w.origin_panel.layer.count()==2 and w.origin_panel.mapping.rowCount()==2
    w.origin_panel.transfer()
    assert w.project==before and w.pending_review
    assert w.ai_panel.reference['series'][0]['color']=='#f27970'
    assert w.workspaces.currentIndex()==w.agent_index
    w.apply_agent()
    assert w.project.datasets==before.datasets
    assert w.project.figure.series[0].color=='#f27970'
    w.undo();assert w.project.figure==before.figure


def test_gui_origin_partial_template_requires_scope_ack(window):
    from test_origin_workflow import analysis_fixture
    from sps import origin
    w,_=window;t=origin.layer_template(analysis_fixture(),'g1:l1')
    w.store_origin_template(t)
    assert w.workspaces.currentIndex()==w.template_index
    dialog=TemplateBindingDialog(w.project,t,w)
    with pytest.raises(ValueError,match='确认'):dialog.operation()
    dialog.partial_ack.setChecked(True)
    assert dialog.operation()['template']['source']['kind']=='origin_partial'
    dialog.close()


def test_gui_ai_offline_rules_review_apply_and_save_config_without_key(window,tmp_path):
    from sps import ai
    w,_=window;before=w.project.clone();panel=w.ai_panel
    panel.key.setText('DUMMY_NOT_SAVED');panel.model.setText('local-test')
    panel.save_config()
    saved=json.loads(panel.settings_path.read_text())
    assert 'DUMMY_NOT_SAVED' not in panel.settings_path.read_text() and 'api_key' not in saved
    panel.offline('uniform')
    assert panel.plan['provider']['mode']=='offline_rules'
    assert w.project==before and w.pending_review
    w.apply_agent();assert w.project.figure.series[0].width==1.8
    assert w.project.datasets==before.datasets and w.project.figure.xlabel==before.figure.xlabel
    w.undo();assert w.project.figure==before.figure


def test_gui_ai_consent_staleness_and_payload_privacy(window):
    w,_=window;panel=w.ai_panel
    panel.model.setText('contract-test');panel.prompt.setText('统一线宽')
    panel.prepare_request();assert panel.prepared and not panel.send_button.isEnabled()
    assert 'datasets' not in panel.outgoing.toPlainText() and w.project.figure.xlabel not in panel.outgoing.toPlainText()
    panel.consent.setChecked(True);assert panel.send_button.isEnabled()
    panel.prompt.setText('重新选择');assert panel.prepared is None and not panel.send_button.isEnabled()
    panel.prepare_request();panel.consent.setChecked(True)
    w.execute([{'op':'set_figure','changes':{'font_size':11}}])
    assert panel.prepared is None and not panel.consent.isChecked()


def test_gui_ai_background_http_contract_then_review(window,app):
    from test_ai import mock_api
    w,_=window;p=w.ai_panel;before=w.project.clone()
    with mock_api() as (url,seen):
        p.base.setText(url);p.model.setText('contract-mock');p.prompt.setText('统一线宽')
        p.key.setText('DUMMY_UI_SECRET');p.prepare_request();p.consent.setChecked(True);p.send()
        import time
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
            if not p.busy and p.plan:break
        assert not p.busy and p.plan,p.status.text()
        assert len(seen)==1 and w.pending_review
        assert p.key.text()=='' and 'DUMMY_UI_SECRET' not in p.outgoing.toPlainText()+p.result.toPlainText()
    assert w.project==before
    w.apply_agent();assert w.project.figure.series[0].width==2.4 and w.project.datasets==before.datasets


def test_gui_ignores_ai_response_when_request_input_changed(window):
    from sps import ai
    w,_=window;panel=w.ai_panel
    panel.model.setText('contract-test');panel.prompt.setText('统一线宽');panel.prepare_request()
    request_hash=panel.prepared['body_sha256']
    plan=ai.offline_plan(w.project)
    panel.prompt.setText('另一个请求')
    panel.receive_network(plan,request_hash)
    assert not w.pending_review and panel.plan is None
    assert '未采用' in panel.status.text()


def test_gui_editor_table_height_restored_after_workspaces(window,app):
    w,_=window
    for index in (w.origin_index,w.ai_index,w.template_index,w.editor_index):
        w.workspaces.setCurrentIndex(index);app.processEvents()
    assert w.middle_splitter.sizes()[1]>=150
