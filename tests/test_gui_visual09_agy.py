import os, tempfile, pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_visual09_navigation_and_inspector(app):
    from sps.gui import MainWindow
    from sps.model import Project

    with tempfile.TemporaryDirectory() as tmp_dir:
        demo = Project()
        win = MainWindow(demo, library_dir=tmp_dir)
        try:
            win.show()
            nav, ws, stack = win.workspace_nav, win.workspaces, win.right_stack
            e_idx, x_idx = win.editor_index, win.export_index
            assert nav.count() == 7 and ws.count() == 7
            for row in range(nav.count()):
                assert bool(nav.item(row).text().strip())
            snap = win.project.to_dict()

            for row in range(7):
                nav.setCurrentRow(row)
                app.processEvents()
                assert ws.currentIndex() == row
                assert win.project.to_dict() == snap
                assert stack.isVisible() if row in (e_idx, x_idx) else not stack.isVisible()

            for idx in range(7):
                ws.setCurrentIndex(idx)
                app.processEvents()
                assert nav.currentRow() == idx
                assert win.project.to_dict() == snap

            nav.setCurrentRow(e_idx)
            app.processEvents()
            assert stack.isVisible()
            assert win.project.to_dict() == snap
        finally:
            win.saved_hash = getattr(win.project, "content_hash", getattr(win.project, "fingerprint", lambda: "h"))()
            app.clipboard().clear()
            win.close()
