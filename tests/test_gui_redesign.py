"""UI behavior acceptance; synthetic documents, no service requests."""
import threading
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence,QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea
from test_gui import app,window
from test_office_gui import wait
from test_origin_gui_v07 import recovery
from sps.ui_helpers import HelpDisclosure
from sps.theme import tokens
from sps.template_ui import TemplateBindingDialog


def test_keyboard_navigation_search_and_view_preferences(window,app):
    w,_=window;before=w.project.fingerprint();w.activateWindow();app.processEvents()
    QTest.keySequence(w,QKeySequence('Ctrl+6'));app.processEvents()
    assert w.workspaces.currentIndex()==w.ai_index
    assert not w.right_stack.isVisible() and not w.bottom_panel.isVisible()
    QTest.keySequence(w,QKeySequence('Ctrl+F'));app.processEvents()
    assert w.workspaces.currentIndex()==w.editor_index and w.project_filter.hasFocus()
    for action,widget in ((w.inspector_action,w.right_stack),(w.data_panel_action,w.bottom_panel)):
        action.trigger();app.processEvents();assert not widget.isVisible()
        w.workspace_nav.setCurrentRow(w.template_index);w.workspace_nav.setCurrentRow(w.editor_index)
        app.processEvents();assert not widget.isVisible()
        action.trigger();app.processEvents();assert widget.isVisible()
    assert w.project.fingerprint()==before


def test_context_help_and_navigation_anchoring_at_compact_size(window,app):
    w,_=window;before=w.project.fingerprint();w.resize(1120,720);app.processEvents()
    anchor=w.workspace_nav.y()
    for index in range(7):
        w.workspace_nav.setCurrentRow(index);app.processEvents()
        assert w.workspace_nav.y()==anchor
        assert w.width()==1120 and w.height()==720
        assert w.workspace_nav.verticalScrollBar().maximum()==0
        assert w.workspaces.widget(index).minimumSizeHint().width()<=w.workspaces.width()
    for help_widget in w.findChildren(HelpDisclosure):
        assert not help_widget.toggle.isChecked()
        help_widget.toggle.click();assert help_widget.toggle.isChecked()
        help_widget.toggle.click();assert help_widget.body.isHidden()
    assert w.project.fingerprint()==before


def test_office_valid_selection_button_states_and_invalidation(window,app):
    w,_=window;p=w.office_panel
    assert not p.reconstruct_button.isEnabled() and not p.save_button.isEnabled()
    r=recovery()
    for column in r['spreadsheets'][0]['columns']:column['data']=[1.,2.]
    p.set_recovery(r);assert p.save_button.isEnabled() and not p.reconstruct_button.isEnabled()
    p.x.setCurrentIndex(0);p.y.setCurrentIndex(1);p.add_pair()
    assert p.reconstruct_button.isEnabled()
    p.clear_pairs();assert not p.reconstruct_button.isEnabled()
    p.source.setText('another-file.opju')
    assert not p.save_button.isEnabled() and not p.reconstruct_button.isEnabled()


def test_real_task_busy_feedback_clears_on_failure(window,app):
    w,_=window;p=w.office_panel;release=threading.Event();entered=threading.Event()
    def work():
        entered.set();release.wait(3);raise ValueError('synthetic reader failure')
    p.work(work,lambda result:None)
    try:
        assert entered.wait(1)
        assert not p.busy_indicator.isHidden() and not p.read_button.isEnabled()
        p.work(lambda:None,lambda result:None);assert len(p.tasks)==1
    finally:
        release.set();wait(app,p)
    assert p.busy_indicator.isHidden() and p.read_button.isEnabled()
    assert 'synthetic reader failure' in p.status.text()


def test_scroll_surfaces_use_light_visual_system(window):
    w,_=window
    for area in w.findChildren(QScrollArea):
        if area.property("no_surface"):
            continue
        if area.widget():
            assert area.widget().objectName()=='scroll_surface'
            assert area.widget().palette().window().color()==QColor(tokens(w.appearance)['window'])


def test_late_created_template_dialog_surface(window,app):
    w,_=window;before=w.project.fingerprint()
    dialog=TemplateBindingDialog(w.project,w.template_panel.selected_template(),w)
    try:
        dialog.show();app.processEvents()
        area=dialog.findChild(QScrollArea)
        assert area.widget().objectName()=='scroll_surface'
        assert area.widget().palette().window().color()==QColor(tokens(w.appearance)['window'])
        assert w.project.fingerprint()==before
    finally:dialog.close()


def test_review_images_fit_when_resized_without_changing_review(window,app):
    w,_=window;before=w.project.fingerprint()
    w.workspaces.setCurrentIndex(w.agent_index);w.preview_agent();app.processEvents()
    assert w.pending_review
    for width in (1510,1120):
        w.resize(width,720);app.processEvents()
        for preview in (w.before_preview,w.after_preview):
            assert not preview.pixmap().isNull()
            assert preview.pixmap().width()<=preview.width()-24
            assert preview.pixmap().height()<=preview.height()-24
    assert w.project.fingerprint()==before
