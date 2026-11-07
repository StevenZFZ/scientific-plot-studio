"""GUI-only disclosure controls; never mutate scientific document state."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QToolButton,QLabel


def style_scroll_surface(area):
    """Name and repolish auto-filled content, including dialogs created later."""
    surface=area.widget()
    if surface:
        surface.setObjectName('scroll_surface')
        surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        surface.style().unpolish(surface)
        surface.style().polish(surface)


class HelpDisclosure(QWidget):
    def __init__(self, text, title='使用说明', parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        self.toggle=QToolButton();self.toggle.setText(title);self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow);self.toggle.setProperty('help',True)
        self.toggle.setAccessibleName(title)
        self.body=QLabel(text);self.body.setTextFormat(Qt.TextFormat.PlainText);self.body.setWordWrap(True)
        self.body.setProperty('muted',True);self.body.hide()
        layout.addWidget(self.toggle,0,Qt.AlignmentFlag.AlignLeft);layout.addWidget(self.body)
        self.toggle.toggled.connect(self.expand)
    def expand(self, checked):
        self.body.setVisible(checked)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
