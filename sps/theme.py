"""Apple-inspired visual system for the desktop shell.

The document itself stays a white scientific page in both appearances; only the
chrome, controls and chrome typography change. Tokens are the single source of
truth so the Qt palette, the stylesheet and the tests never drift apart.
"""
from pathlib import Path
from string import Template

ASSETS = Path(__file__).parent / "assets"

# 13 px body / 11 px caption / 20 px display, matching desktop macOS metrics.
# Latin first, then Simplified Chinese. Arial ships everywhere and matches most
# journal requirements; 思源黑体 (Source Han Sans / Noto Sans CJK SC) is used for
# Chinese when installed, with PingFang SC as the macOS fallback.
FONT_STACK = '"Arial", "Source Han Sans SC", "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Helvetica Neue", "Microsoft YaHei UI", sans-serif'

LIGHT = {
    "mode": "light",
    "window": "#f5f5f7",
    "chrome": "#fbfbfd",
    "sidebar": "#ececef",
    "card": "#ffffff",
    "card_border": "#e3e3e8",
    "hairline": "#dcdce0",
    "field": "#ffffff",
    "field_border": "#d2d2d7",
    "text": "#1d1d1f",
    "text2": "#6e6e73",
    "text3": "#8e8e93",
    "accent": "#0071e3",
    "accent_hover": "#0077ed",
    "accent_press": "#0062c4",
    "accent_soft": "#e8f1fc",
    "accent_border": "#b9d7f7",
    "hover": "#f0f0f3",
    "hover_sidebar": "#e3e3e7",
    "segment": "#e9e9ec",
    "table_head": "#f7f7f9",
    "grid": "#ededf0",
    "scroll": "#000000",
    "scroll_alpha": "0.20",
    "scroll_hover_alpha": "0.34",
    "tooltip": "#fbfbfd",
    "danger": "#ff3b30",
    "success": "#34c759",
    "warning": "#ff9f0a",
    "shadow": "rgba(0, 0, 0, 0.10)",
    "shadow_soft": "rgba(0, 0, 0, 0.05)",
    "check": (ASSETS / "check.svg").as_posix(),
    "chevron": (ASSETS / "chevron-down.svg").as_posix(),
    "chevron_up": (ASSETS / "chevron-up.svg").as_posix(),
}

DARK = {
    "mode": "dark",
    "window": "#1c1c1e",
    "chrome": "#232326",
    "sidebar": "#202024",
    "card": "#2c2c2e",
    "card_border": "#3a3a3c",
    "hairline": "#38383a",
    "field": "#1c1c1e",
    "field_border": "#48484a",
    "text": "#f5f5f7",
    "text2": "#a1a1a6",
    "text3": "#8e8e93",
    "accent": "#0a84ff",
    "accent_hover": "#3395ff",
    "accent_press": "#0069d9",
    "accent_soft": "#1b3b5c",
    "accent_border": "#2c5c8f",
    "hover": "#3a3a3c",
    "hover_sidebar": "#2a2a2d",
    "segment": "#3a3a3c",
    "table_head": "#262629",
    "grid": "#333336",
    "scroll": "#ffffff",
    "scroll_alpha": "0.24",
    "scroll_hover_alpha": "0.40",
    "tooltip": "#2c2c2e",
    "danger": "#ff453a",
    "success": "#30d158",
    "warning": "#ffd60a",
    "shadow": "rgba(0, 0, 0, 0.55)",
    "shadow_soft": "rgba(0, 0, 0, 0.35)",
    "check": (ASSETS / "check.svg").as_posix(),
    "chevron": (ASSETS / "chevron-down-dark.svg").as_posix(),
    "chevron_up": (ASSETS / "chevron-up-dark.svg").as_posix(),
}

PALETTES = {"light": LIGHT, "dark": DARK}

_STYLE = Template("""
QMainWindow, QDialog {
    background: $window;
}
QWidget {
    color: $text;
    font-family: $font;
    font-size: 13px;
    font-weight: 400;
}
QLabel { color: $text; background: transparent; }
QLabel[muted="true"] { color: $text2; font-size: 12px; }
QLabel[heading="true"], QLabel#workspace_title {
    color: $text;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.2px;
}
QLabel[status="true"] {
    background: $accent_soft;
    color: $accent;
    border: 1px solid $accent_border;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#section_label {
    color: $text3;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.4px;
}
QLabel#brand_title { color: $text; font-size: 14px; font-weight: 700; letter-spacing: -0.2px; }
QLabel#brand_subtitle { color: $text3; font-size: 11px; }

/* ---------- window chrome ---------- */
QMenuBar {
    background: $chrome;
    border-bottom: 1px solid $hairline;
}
QMenuBar::item { padding: 5px 10px; background: transparent; border-radius: 5px; }
QMenuBar::item:selected { background: $hover; color: $text; }

QToolBar#main_toolbar {
    background: $chrome;
    border: 0;
    border-bottom: 1px solid $hairline;
    padding: 7px 12px;
    spacing: 3px;
}
QToolBar#main_toolbar::separator { background: $hairline; width: 1px; margin: 6px 8px; }
QToolButton {
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 4px 7px;
    min-height: 20px;
    color: $text;
    font-size: 12px;
    font-weight: 500;
}
QToolButton:hover { background: $hover; }
QToolButton:pressed { background: $segment; }
QToolButton:checked { background: $accent_soft; color: $accent; }
QToolButton:disabled { color: $text3; }
QToolButton[help="true"] { color: $text2; padding: 2px 3px; font-size: 12px; }
QToolButton#nav_button { padding: 0; border-radius: 6px; }
QToolButton#nav_button:hover { background: $hover; }
QToolButton#nav_button:checked { background: $accent_soft; }
QToolButton#toolbar_text {
    padding: 4px 9px;
    font-size: 12px;
    color: $text;
    border: 1px solid transparent;
}
QToolButton#toolbar_text:hover { background: $hover; }

QPushButton {
    background: $card;
    color: $text;
    border: 1px solid $field_border;
    border-radius: 7px;
    padding: 5px 12px;
    min-height: 20px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $segment; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { color: $text3; background: $window; border-color: $card_border; }
QPushButton[primary="true"] {
    color: #ffffff;
    background: $accent;
    border: 1px solid $accent;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[primary="true"]:pressed { background: $accent_press; border-color: $accent_press; }
QPushButton[primary="true"]:disabled { background: $accent_border; border-color: $accent_border; color: #ffffff; }
QPushButton[variant="sidebar"] {
    background: transparent;
    border: 0;
    text-align: left;
    padding: 5px 9px;
    color: $text;
    font-weight: 500;
    font-size: 12px;
}
QPushButton[variant="sidebar"]:hover { background: $hover_sidebar; }
QPushButton[variant="sidebar"][accent="true"] { color: $accent; font-weight: 600; }
QPushButton[variant="sidebar"][muted="true"] { color: $text2; }
QPushButton[variant="sidebar"]:pressed { background: $segment; }
QPushButton[variant="plain"] {
    background: transparent;
    border: 0;
    color: $accent;
    padding: 3px 6px;
}
QPushButton[variant="plain"]:hover { background: $accent_soft; }

/* ---------- fields ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: $field;
    color: $text;
    border: 1px solid $field_border;
    border-radius: 7px;
    padding: 4px 8px;
    min-height: 20px;
    font-size: 13px;
    selection-background-color: $accent;
    selection-color: #ffffff;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: $text3; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: $window; color: $text3; border-color: $card_border;
}
QLineEdit#search_field {
    background: $segment;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px 9px 4px 26px;
    background-image: url($magnifier);
    background-repeat: no-repeat;
    background-position: left 7px center;
    font-size: 12px;
}
QLineEdit#search_field:focus { background: $field; border-color: $accent; }
QComboBox { padding-right: 20px; }
QComboBox::drop-down { border: 0; width: 18px; }
QComboBox::down-arrow { image: url($chevron); width: 9px; height: 9px; }
QComboBox QAbstractItemView {
    background: $card;
    color: $text;
    border: 1px solid $card_border;
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: $accent;
    selection-color: #ffffff;
}
QSpinBox, QDoubleSpinBox { padding-right: 18px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 16px; border: 0; border-top-right-radius: 6px; background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 16px; border: 0; border-bottom-right-radius: 6px; background: transparent;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: $hover; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url($chevron_up); width: 8px; height: 8px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url($chevron); width: 8px; height: 8px; }

/* ---------- cards ---------- */
QGroupBox {
    background: transparent;
    border: 0;
    border-top: 1px solid $hairline;
    border-radius: 0;
    margin-top: 20px;
    padding: 9px 0 0;
    font-size: 13px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0;
    top: 0;
    padding: 0 0 6px 0;
    color: $text2;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
}

/* ---------- tabs / segmented controls ---------- */
QFrame { border: 0; }
QFrame#segmented { background: $segment; border-radius: 8px; }
QFrame#segmented QToolButton {
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 500;
    color: $text2;
    min-height: 16px;
}
QFrame#segmented QToolButton:hover { color: $text; }
QFrame#segmented QToolButton:checked {
    background: $card;
    color: $text;
    border: 1px solid $card_border;
    font-weight: 600;
}
QTabWidget::pane { background: transparent; border: 0; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: $text2;
    border: 0;
    padding: 4px 11px;
    margin: 2px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
}
QTabBar::tab:hover:!selected { background: $hover; color: $text; }
QTabBar::tab:selected { background: $card; color: $text; font-weight: 600; }
QTabBar::tab:disabled { color: $text3; }
QTabWidget#property_tabs QTabBar, QTabWidget#bottom_tabs QTabBar {
    background: $segment;
    border-radius: 8px;
}
QTabWidget#property_tabs QTabBar::tab, QTabWidget#bottom_tabs QTabBar::tab {
    padding: 4px 9px;
    margin: 2px;
    border-radius: 6px;
    font-size: 12px;
}
QTabWidget#property_tabs QTabBar::tab:selected,
QTabWidget#bottom_tabs QTabBar::tab:selected {
    background: $card;
    color: $text;
    border: 1px solid $card_border;
}
QTabWidget#bottom_tabs::pane { background: transparent; border: 0; }
QTabBar#graph_tabs { background: transparent; }
QTabBar#graph_tabs::tab {
    background: $segment;
    color: $text2;
    border-radius: 7px;
    padding: 3px 10px;
    margin-right: 4px;
    font-size: 12px;
}
QTabBar#graph_tabs::tab:selected { background: $card; color: $accent; font-weight: 600; }

/* ---------- sidebar ---------- */
QWidget#project_sidebar {
    background: $sidebar;
    border-right: 1px solid $hairline;
}
QListWidget#workspace_nav {
    background: transparent;
    border: 0;
    padding: 2px 0;
    outline: 0;
}
QListWidget#workspace_nav::item {
    height: 30px;
    padding: 0 8px;
    margin: 1px 6px;
    border-radius: 7px;
    color: $text;
    font-size: 13px;
    font-weight: 500;
}
QListWidget#workspace_nav::item:hover { background: $hover_sidebar; }
QListWidget#workspace_nav::item:selected { background: $accent_soft; color: $accent; font-weight: 600; }
QListWidget#workspace_nav::item:disabled { color: $text3; }

QTreeWidget {
    background: transparent;
    border: 0;
    padding: 0;
    outline: 0;
    color: $text;
    font-size: 12px;
}
QTreeWidget::item { height: 25px; padding: 1px 3px; border-radius: 5px; }
QTreeWidget::item:hover { background: $hover_sidebar; }
QTreeWidget::item:selected { background: $accent_soft; color: $accent; font-weight: 500; }

QListWidget#template_list {
    border: 0;
    background: transparent;
    padding: 6px;
    outline: 0;
}
QListWidget#template_list::item {
    border: 1px solid $hairline;
    border-radius: 6px;
    background: $card;
    padding: 10px;
    margin-bottom: 6px;
}
QListWidget#template_list::item:hover { border-color: $accent_border; }
QListWidget#template_list::item:selected { background: $accent_soft; border-color: $accent; color: $text; }

/* ---------- data ---------- */
QTableWidget {
    background: $card;
    alternate-background-color: $table_head;
    border: 1px solid $hairline;
    border-radius: 0;
    gridline-color: $grid;
    selection-background-color: $accent_soft;
    selection-color: $text;
    font-size: 12px;
    outline: 0;
}
QHeaderView::section {
    background: $table_head;
    color: $text2;
    border: 0;
    border-right: 1px solid $grid;
    border-bottom: 1px solid $card_border;
    padding: 5px 8px;
    font-size: 11px;
    font-weight: 600;
}
QHeaderView { background: $table_head; }
QTableCornerButton::section { background: $table_head; border: 0; border-bottom: 1px solid $card_border; }

QPlainTextEdit {
    background: $card;
    color: $text;
    border: 1px solid $card_border;
    border-radius: 8px;
    padding: 8px;
    font-size: 12px;
    selection-background-color: $accent;
    selection-color: #ffffff;
}
QPlainTextEdit:focus { border-color: $accent; }
QPlainTextEdit[code="true"] { background: $table_head; font-size: 11px; }

/* ---------- canvas ---------- */
QWidget#figure_page { background: $window; }
QWidget#canvas_scroll { background: $window; border: 0; }
QScrollArea { border: 0; background: $window; }
QWidget#scroll_surface { background: $window; }
QWidget#inspector_surface { background: $window; }
QFrame#hairline { background: $hairline; border: 0; }
QFrame#preview_card { background: $card; border: 1px solid $hairline; border-radius: 0; }
QLabel#preview_card { background: $card; border: 1px solid $hairline; border-radius: 0; color: $text3; }

/* ---------- feedback ---------- */
QCheckBox::indicator, QTreeWidget::indicator, QTableWidget::indicator {
    width: 15px; height: 15px;
    border: 1px solid $field_border;
    border-radius: 4px;
    background: $field;
}
QCheckBox::indicator:hover, QTreeWidget::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked, QTreeWidget::indicator:checked, QTableWidget::indicator:checked {
    background: $accent;
    border-color: $accent;
    image: url($check);
}
QCheckBox::indicator:disabled { background: $window; border-color: $card_border; }

QProgressBar {
    border: 0;
    border-radius: 2px;
    background: $segment;
    text-align: center;
    height: 4px;
    font-size: 10px;
    color: $text2;
}
QProgressBar::chunk { background: $accent; border-radius: 2px; }

QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical {
    background: rgba($scroll_rgb, $scroll_alpha);
    border-radius: 4px;
    min-height: 26px;
}
QScrollBar::handle:vertical:hover { background: rgba($scroll_rgb, $scroll_hover_alpha); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: rgba($scroll_rgb, $scroll_alpha);
    border-radius: 4px;
    min-width: 26px;
}
QScrollBar::handle:horizontal:hover { background: rgba($scroll_rgb, $scroll_hover_alpha); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QStatusBar {
    background: $chrome;
    border-top: 1px solid $hairline;
    padding: 3px 10px;
}
QStatusBar QLabel { color: $text2; font-size: 11px; }
QStatusBar::item { border: 0; }

QSplitter::handle { background: $hairline; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QSplitter::handle:hover { background: $accent_border; }

QToolTip {
    background: $tooltip;
    color: $text;
    border: 1px solid $card_border;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 11px;
}
QMenu {
    background: $card;
    border: 1px solid $card_border;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item { padding: 5px 14px; border-radius: 5px; }
QMenu::item:selected { background: $accent; color: #ffffff; }
QMenu::separator { height: 1px; background: $hairline; margin: 4px 8px; }

QMessageBox, QInputDialog, QFileDialog { background: $window; }
QDialogButtonBox QPushButton { min-width: 76px; }
""")


def tokens(mode="light"):
    return PALETTES.get(mode, LIGHT)


def stylesheet(mode="light"):
    values = dict(tokens(mode))
    values["font"] = FONT_STACK
    values["magnifier"] = (ASSETS / ("magnifier-dark.svg" if mode == "dark" else "magnifier.svg")).as_posix()
    values["scroll_rgb"] = "255, 255, 255" if mode == "dark" else "0, 0, 0"
    return _STYLE.substitute(values)


_APPLIED = {"app": None, "mode": None}


def apply_theme(app, mode="light"):
    """Apply palette + stylesheet to the application; returns the applied mode."""
    from PySide6.QtGui import QColor, QPalette

    if _APPLIED["app"] is app and _APPLIED["mode"] == mode:
        return mode
    palette = tokens(mode)
    qpalette = QPalette(app.palette())
    roles = {
        QPalette.ColorRole.Window: palette["window"],
        QPalette.ColorRole.WindowText: palette["text"],
        QPalette.ColorRole.Base: palette["card"],
        QPalette.ColorRole.AlternateBase: palette["table_head"],
        QPalette.ColorRole.Text: palette["text"],
        QPalette.ColorRole.Button: palette["card"],
        QPalette.ColorRole.ButtonText: palette["text"],
        QPalette.ColorRole.Highlight: palette["accent_soft"],
        QPalette.ColorRole.HighlightedText: palette["text"],
        QPalette.ColorRole.ToolTipBase: palette["tooltip"],
        QPalette.ColorRole.ToolTipText: palette["text"],
        QPalette.ColorRole.PlaceholderText: palette["text3"],
    }
    for role, color in roles.items():
        qpalette.setColor(role, QColor(color))
    app.setPalette(qpalette)
    # Clearing first forces item views and segmented controls to drop cached
    # light-mode style options when the appearance changes at runtime.
    app.setStyleSheet("")
    app.setStyleSheet(stylesheet(mode))
    for widget in app.allWidgets():
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()
    _APPLIED["app"] = app
    _APPLIED["mode"] = mode
    return mode


def system_mode(app=None):
    """Best-effort reading of the host appearance before SPS applies its own."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    app = app or QApplication.instance()
    if app is None:
        return "light"
    return "dark" if app.palette().color(QPalette.ColorRole.Window).lightness() < 128 else "light"


# Backwards-compatible constant used by older call sites and tests.
STYLE = stylesheet("light")
