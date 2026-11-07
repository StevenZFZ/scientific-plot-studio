"""Small native controls; no document mutation or external service calls."""
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QRect, qInstallMessageHandler, QtMsgType
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton, QColorDialog,QLabel,QSizePolicy


class AspectPreview(QLabel):
    """Resize a review image without letting its pixel size dictate the layout."""
    def __init__(self,text):
        super().__init__(text);self._source=QPixmap()
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
    def setPixmap(self,pixmap):
        self._source=QPixmap(pixmap);self.fit_image()
    def clear(self):
        self._source=QPixmap();super().clear()
    def resizeEvent(self,event):
        super().resizeEvent(event);self.fit_image()
    def fit_image(self):
        if not self._source.isNull():
            target=QSize(max(1,self.width()-24),max(1,self.height()-24))
            super().setPixmap(self._source.scaled(target,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))


class FigurePage(QWidget):
    """Paper surface: the canvas is fitted to the document aspect ratio, with an
    Apple-style page shadow. Zoom is a view-only scale; exports keep their mm size.
    """
    PAGE_MARGIN = 28

    def __init__(self, canvas):
        super().__init__()
        self.setObjectName("figure_page")
        self.canvas = canvas
        self.ratio = 160 / 110
        self.width_mm, self.height_mm = 160.0, 110.0
        self.zoom = None  # None = fit window, otherwise 1.0 / 1.5 / 2.0
        self.setMinimumSize(260, 220)
        self.canvas.setStyleSheet("border:0; background:white;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.PAGE_MARGIN, self.PAGE_MARGIN, self.PAGE_MARGIN, self.PAGE_MARGIN)
        layout.addWidget(canvas, 0, Qt.AlignmentFlag.AlignCenter)

    def set_aspect(self, width, height):
        self.ratio = width / height
        self.width_mm, self.height_mm = float(width), float(height)
        self.fit_canvas()

    def set_zoom(self, zoom):
        """zoom: None for fit, or a scale factor relative to the physical size."""
        self.zoom = zoom
        self.fit_canvas()
        self.update()

    def zoom_text(self):
        if self.zoom is None:
            return "适应窗口"
        return f"{round(self.zoom * 100)}%"

    def _page_size(self):
        if self.zoom is None:
            available_w = max(120, self.width() - 2 * self.PAGE_MARGIN)
            available_h = max(120, self.height() - 2 * self.PAGE_MARGIN)
            width = min(available_w, available_h * self.ratio)
        else:
            # 96 dpi reference: 100% shows the figure at its physical size.
            width = self.width_mm / 25.4 * 96 * self.zoom
        height = width / self.ratio
        return max(100, int(width)), max(80, int(height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_canvas()

    def fit_canvas(self):
        width, height = self._page_size()
        size = QSize(width, height)
        if size != self.canvas.size():
            self.canvas.setFixedSize(size)
        if self.zoom is None:
            minimum = QSize(260, 220)
        else:
            minimum = QSize(width + 2 * self.PAGE_MARGIN, height + 2 * self.PAGE_MARGIN)
        if minimum != self.minimumSize():
            self.setMinimumSize(minimum)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self.palette().window())
        page = QRect(self.canvas.geometry()).adjusted(0, 0, 0, 0)
        if page.isEmpty():
            painter.end()
            return
        dark = self.palette().window().color().lightness() < 128
        # Layered translucent rects stand in for a blur shadow without extra widgets.
        for spread, alpha in ((5, 10 if dark else 8), (3, 22 if dark else 16), (1, 34 if dark else 26)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(page.adjusted(-spread, -spread + 2, spread, spread + 2), 5, 5)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QColor(0, 0, 0, 40 if dark else 22))
        painter.drawRoundedRect(page, 3, 3)
        painter.end()


class ColorField(QWidget):
    def __init__(self, value="#287d95"):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.edit = QLineEdit(value)
        self.swatch = QPushButton()
        self.swatch.setFixedWidth(34)
        self.swatch.setToolTip("选择颜色")
        layout.addWidget(self.swatch)
        layout.addWidget(self.edit, 1)
        self.swatch.clicked.connect(self.choose)
        self.edit.textChanged.connect(self.update_swatch)
        self.update_swatch()

    def text(self):
        return self.edit.text()

    def setText(self, value):
        self.edit.setText(value)

    def update_swatch(self):
        value = self.text()
        valid = len(value) == 7 and value.startswith("#") and QColor(value).isValid()
        self.swatch.setStyleSheet(
            f"background:{value if valid else '#ffffff'}; border:1px solid rgba(0,0,0,0.18); border-radius:6px;")

    def choose(self):
        selected = QColorDialog.getColor(QColor(self.text()), self, "选择曲线 / 文字颜色")
        if selected.isValid():
            self.setText(selected.name())


def svg_pixmap(path, width=1200):
    """Render the actual exported SVG with the local Qt SVG engine, not an imitation."""
    issues = []
    previous = None

    def capture(kind, context, message):
        if str(context.category).startswith("qt.svg") and kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
            issues.append(message)
        elif previous:
            previous(kind, context, message)
        else:
            import sys
            print(message, file=sys.stderr)

    previous = qInstallMessageHandler(capture)
    try:
        renderer = QSvgRenderer(str(Path(path)))
        if not renderer.isValid():
            raise ValueError("本机 SVG 阅读器无法加载该文件")
        bounds = renderer.viewBoxF()
        if bounds.width() <= 0 or bounds.height() <= 0:
            raise ValueError("SVG 画布尺寸无效")
        height = max(1, round(width * bounds.height() / bounds.width()))
        if width * height > 8_000_000:
            raise ValueError("SVG 预览尺寸过大")
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
    finally:
        qInstallMessageHandler(previous)
    if issues:
        raise ValueError("SVG 阅读器报告问题：" + "; ".join(dict.fromkeys(issues)))
    return QPixmap.fromImage(image)
