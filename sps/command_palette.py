"""Spotlight-style command palette and shortcut sheet.

Both are pure UI helpers: they only call the callbacks handed to them, so no
document state is touched until the chosen command itself runs.
"""
from dataclasses import dataclass

from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from .icons import icon
from .theme import tokens


@dataclass
class Command:
    title: str
    run: object
    subtitle: str = ""
    shortcut: str = ""
    icon_name: str = "command"
    keywords: str = ""
    group: str = "操作"
    enabled: bool = True

    def score(self, query):
        """Higher is better; 0 means no match. Title hits beat keyword hits."""
        query = query.strip().casefold()
        if not query:
            return 1
        title = self.title.casefold()
        if title.startswith(query):
            return 100
        if query in title:
            return 80
        if query in f"{self.subtitle} {self.keywords} {self.group}".casefold():
            return 50
        # subsequence match, the way Spotlight tolerates skipped characters
        haystack = f"{title} {self.subtitle} {self.keywords} {self.group}".casefold()
        it = iter(haystack)
        return 20 if all(char in it for char in query) else 0

    def matches(self, query):
        return self.score(query) > 0


class CommandPalette(QDialog):
    """Frameless search panel: type, arrow, Return."""

    def __init__(self, commands, parent=None, placeholder="搜索命令、工作区或对象…"):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.commands = [c for c in commands if c.enabled]
        mode = getattr(parent, "appearance", "light")
        self.mode = mode if mode in ("light", "dark") else "light"
        self._build(placeholder)
        self.resize(600, 420)
        self.refresh("")

    def _build(self, placeholder):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        self.card = QFrame(self)
        self.card.setObjectName("palette_card")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 90 if self.mode == "light" else 180))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        self.query = QLineEdit()
        self.query.setObjectName("palette_query")
        self.query.setPlaceholderText(placeholder)
        self.query.setClearButtonEnabled(True)
        self.query.textChanged.connect(self.refresh)
        self.query.installEventFilter(self)
        layout.addWidget(self.query)
        self.list = QListWidget()
        self.list.setObjectName("palette_list")
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        layout.addWidget(self.list, 1)
        self.hint = QLabel("↑↓ 选择    ⏎ 执行    esc 关闭")
        self.hint.setObjectName("palette_hint")
        layout.addWidget(self.hint)
        self._style()

    def _style(self):
        t = tokens(self.mode)
        self.setStyleSheet(f"""
            QFrame#palette_card {{
                background: {t['card']};
                border: 1px solid {t['card_border']};
                border-radius: 14px;
            }}
            QLineEdit#palette_query {{
                background: transparent;
                border: 0;
                border-bottom: 1px solid {t['hairline']};
                border-radius: 0;
                padding: 6px 4px 10px;
                font-size: 19px;
                color: {t['text']};
            }}
            QLineEdit#palette_query:focus {{ border-bottom: 1px solid {t['accent']}; }}
            QListWidget#palette_list {{
                background: transparent; border: 0; outline: 0; padding: 2px;
            }}
            QListWidget#palette_list::item {{
                border-radius: 8px; padding: 0; margin: 1px 0;
            }}
            QListWidget#palette_list::item:selected {{ background: {t['accent_soft']}; }}
            QLabel#palette_hint {{ color: {t['text3']}; font-size: 11px; }}
            QLabel#row_title {{ color: {t['text']}; font-size: 13px; font-weight: 500; background: transparent; }}
            QLabel#row_sub {{ color: {t['text3']}; font-size: 11px; background: transparent; }}
            QLabel#row_key {{ color: {t['text3']}; font-size: 11px; background: transparent; }}
        """)

    def refresh(self, text):
        self.list.clear()
        ranked = [(c.score(text), order, c) for order, c in enumerate(self.commands)]
        visible = [c for score, _, c in sorted((r for r in ranked if r[0] > 0),
                                               key=lambda r: (-r[0], r[1]))][:40]
        for command in visible:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 52 if command.subtitle else 40))
            item.setData(Qt.ItemDataRole.UserRole, command)
            self.list.addItem(item)
            self.list.setItemWidget(item, self._row(command))
        if visible:
            self.list.setCurrentRow(0)
        self.hint.setText(f"{len(visible)} 项结果   ↑↓ 选择    ⏎ 执行    esc 关闭" if text
                          else "↑↓ 选择    ⏎ 执行    esc 关闭")
        self._fit_height(len(visible))

    def _fit_height(self, count):
        rows = sum(52 if c.subtitle else 40 for c in self.commands if c.matches(self.query.text()))
        content = 96 + min(rows, 320) + 34
        height = max(196, min(420, content + 36))
        if height != self.height():
            self.resize(self.width(), height)

    def _row(self, command):
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(icon(command.icon_name, tokens(self.mode)["text3"]).pixmap(17, 17))
        layout.addWidget(mark)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.setContentsMargins(0, 0, 0, 0)
        title = QLabel(command.title)
        title.setObjectName("row_title")
        text.addWidget(title)
        if command.subtitle:
            sub = QLabel(command.subtitle)
            sub.setObjectName("row_sub")
            text.addWidget(sub)
        layout.addLayout(text, 1)
        if command.shortcut:
            key = QLabel(command.shortcut)
            key.setObjectName("row_key")
            layout.addWidget(key)
        return row

    def _activate(self, item):
        command = item.data(Qt.ItemDataRole.UserRole)
        if command is None:
            return
        self.accept()
        command.run()

    def eventFilter(self, watched, event):
        if watched is self.query and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                count = self.list.count()
                if count:
                    step = 1 if key == Qt.Key.Key_Down else -1
                    self.list.setCurrentRow((self.list.currentRow() + step) % count)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.list.currentItem()
                if item:
                    self._activate(item)
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.query.setFocus()
        parent = self.parentWidget()
        if parent is not None:
            frame = parent.window().frameGeometry()
            self.move(frame.center().x() - self.width() // 2,
                      frame.top() + max(60, int(frame.height() * 0.18)))


class ShortcutsSheet(QDialog):
    """Keyboard reference as a sheet, grouped the way macOS lists shortcuts."""

    GROUPS = [
        ("工作区", [("图形编辑器", "⌘1"), ("模板库", "⌘2"), ("导出与校验", "⌘3"),
                    ("风格审查", "⌘4"), ("Origin 样式", "⌘5"), ("AI 助手", "⌘6"),
                    ("数据与 Office", "⌘7")]),
        ("文件与编辑", [("新建", "⌘N"), ("打开", "⌘O"), ("保存", "⌘S"), ("另存为", "⇧⌘S"),
                        ("导入数据", "⌘I"), ("撤销", "⌘Z"), ("重做", "⇧⌘Z")]),
        ("查找与面板", [("命令面板", "⌘K"), ("查找图形对象", "⌘F"), ("属性面板", "⇧⌘P"),
                        ("数据与操作记录", "⌘J"), ("折叠侧栏", "⌥⌘S"), ("快捷键", "⌘/")]),
        ("图形与 Office", [("复制图形+数据", "⇧⌘C"), ("粘贴可编辑工程", "⇧⌘V"),
                           ("复制图像到 Office", "⌥⌘C"), ("导出与校验", "⌘E")]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("键盘快捷键")
        mode = getattr(parent, "appearance", "light")
        self.mode = mode if mode in ("light", "dark") else "light"
        self.setMinimumSize(880, 540)
        t = tokens(self.mode)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)
        title = QLabel("键盘快捷键")
        title.setObjectName("workspace_title")
        layout.addWidget(title)
        subtitle = QLabel("所有编辑都写入可撤销事务；快捷键只改变视图或触发同一命令。")
        subtitle.setProperty("muted", True)
        layout.addWidget(subtitle)
        columns = QHBoxLayout()
        columns.setSpacing(14)
        for index, (group, rows) in enumerate(self.GROUPS):
            column = QVBoxLayout()
            column.setSpacing(6)
            heading = QLabel(group.upper())
            heading.setObjectName("section_label")
            column.addWidget(heading)
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {t['card']}; border: 1px solid {t['card_border']}; border-radius: 10px; }}")
            card.setMinimumWidth(184)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.setSpacing(2)
            for name, keys in rows:
                line = QHBoxLayout()
                line.setContentsMargins(0, 3, 0, 3)
                label = QLabel(name)
                label.setStyleSheet(f"color:{t['text']}; font-size:12px; border:0;")
                key = QLabel(keys)
                key.setStyleSheet(f"color:{t['text3']}; font-size:12px; border:0;")
                line.addWidget(label, 1)
                line.addWidget(key)
                card_layout.addLayout(line)
            column.addWidget(card)
            column.addStretch()
            columns.addLayout(column, 1)
        layout.addLayout(columns, 1)
        close = QLabel("按 esc 关闭")
        close.setStyleSheet(f"color:{t['text3']}; font-size:11px;")
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
