"""Dense native desktop: object editor, export workbench, reviewable style/Agent workspace."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import io
import json
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QStandardPaths, QTimer,QEvent,Signal,QSettings
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPixmap, QPainter, QColor, QPalette, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox,
    QCheckBox, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QPlainTextEdit,
    QGroupBox, QFileDialog, QMessageBox, QDialog, QDialogButtonBox, QScrollArea,
    QInputDialog,QAbstractItemView, QToolBar, QHeaderView, QStackedWidget, QSizePolicy, QAbstractSpinBox, QListWidget, QListWidgetItem,QTabBar,QProgressBar,
    QToolButton, QFrame, QButtonGroup,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from .model import Project, Series, Annotation, uid, demo, load, save, read_json, write_json, COLORS
from .data import import_table
from .commands import Session, style_from_project
from .render import draw, preflight, export_bundle
from .bridge import capabilities
from .widgets import ColorField, svg_pixmap, FigurePage, AspectPreview
from .ui_helpers import HelpDisclosure,style_scroll_surface
from .review import review_rows, selected_operations, display_value
from . import __version__


from .theme import apply_theme, system_mode, tokens
from .icons import icon
from .command_palette import Command, CommandPalette, ShortcutsSheet
from . import templates
from .template_ui import CaptureTemplateDialog, TemplateBindingDialog, TemplateLibraryPanel
from .workflow_ui import OriginPanel, AIPanel
from .office_ui import OfficePanel
from .publication_ui import AxesDialog,PublicationDialog


def label(text, muted=False):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setProperty("muted", muted)
    return widget


def button(text, fn, primary=False, name=None, icon_name=None):
    widget = QPushButton(text)
    widget.clicked.connect(fn)
    if icon_name:
        widget.setIcon(icon(icon_name))
    widget.setProperty("primary", primary)
    if name:
        widget.setObjectName(name)
    return widget


def spin(value, low, high, step=1):
    w = QDoubleSpinBox()
    w.setRange(low, high)
    w.setDecimals(2)
    w.setSingleStep(step)
    w.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
    w.setValue(value)
    return w


def combo(values):
    w = QComboBox()
    w.addItems(values)
    return w


def enum_combo(pairs):
    widget = QComboBox()
    for title, value in pairs:
        widget.addItem(title, value)
    return widget


PLOT_TYPES = [("折线", "line"), ("散点", "scatter"), ("柱状", "bar"), ("Y 误差棒", "errorbar")]

# Captured before SPS applies its own palette, so "跟随系统" stays meaningful.
_SYSTEM_APPEARANCE = None


class ViewToolbar(NavigationToolbar2QT):
    # Matplotlib's stock Customize/Save bypass the editable model and validated
    # export pipeline. Navigation is view-only; all edits/exports use SPS controls.
    toolitems = [item for item in NavigationToolbar2QT.toolitems
                 if item[3] in ("home", "back", "forward", "pan", "zoom") or item[0] is None]


class CheckerPreview(QLabel):
    def __init__(self):
        super().__init__()
        self.original = QPixmap()
        self.background_mode = "checker"
        self.empty_text = "尚无预览"
        self.setMinimumSize(200, 180)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_image(self, pixmap):
        self.original = pixmap
        self.update()

    def set_background(self, mode):
        if mode not in ("checker", "white", "black"):
            raise ValueError("不支持的预览背景")
        self.background_mode = mode
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        if self.original.isNull():
            # No image yet: a flat surface and one hairline beat a heavy checkerboard.
            # Child palettes do not carry the window role, so read the top-level one.
            surface = self.window().palette()
            p.fillRect(self.rect(), surface.window())
            p.setPen(surface.color(QPalette.ColorRole.Mid))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        elif self.background_mode == "checker":
            for y in range(0, self.height(), 16):
                for x in range(0, self.width(), 16):
                    p.fillRect(x, y, 16, 16, QColor("#e3e8ec" if (x // 16 + y // 16) % 2 else "#f8fafb"))
        else:
            p.fillRect(self.rect(), QColor(self.background_mode))
        if not self.original.isNull():
            pix = self.original.scaled(self.size() - QSize(24, 24), Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - pix.width()) // 2, (self.height() - pix.height()) // 2, pix)
        else:
            p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
        p.end()


class MappingDialog(QDialog):
    def __init__(self, dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入数据 · 选择绘图列")
        self.resize(440, 290)
        layout = QVBoxLayout(self)
        layout.addWidget(label(f"{dataset.name} · {len(next(iter(dataset.columns.values())))} 行"))
        form = QFormLayout()
        names = list(dataset.columns)
        self.x = combo(names)
        self.y = combo(names)
        self.y.setCurrentIndex(1)
        self.error = combo(["无"] + names)
        self.kind = enum_combo(PLOT_TYPES)
        form.addRow("X 数据列", self.x)
        form.addRow("Y 数据列", self.y)
        form.addRow("Y 误差列", self.error)
        form.addRow("图形类型", self.kind)
        layout.addLayout(form)
        layout.addWidget(label("仅接受带表头的数值 CSV/TSV；不推断单位、缺失值或误差含义。", True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("生成图形")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def series(self, dataset, index):
        return Series(uid("series"), dataset.id, self.x.currentText(), self.y.currentText(),
                      label=self.y.currentText(), kind=self.kind.currentData(), color=COLORS[index % len(COLORS)],
                      y_error="" if self.error.currentIndex() == 0 else self.error.currentText())


class MainWindow(QMainWindow):
    def __init__(self, project=None, library_dir=None):
        super().__init__()
        self.session = Session(project or demo())
        directory = library_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "templates"
        self.template_library = templates.TemplateLibrary(directory)
        self._pending_visibility = {}
        self.visibility_timer = QTimer(self)
        self.visibility_timer.setSingleShot(True)
        self.visibility_timer.timeout.connect(self.flush_tree_visibility)
        self.project_path = None
        self.figure_path = None
        self.figure_sha = None
        self.figure_links_root = None
        self.saved_hash = self.session.project.fingerprint()
        self.active_id = None
        self.dataset_id = None
        self.pending_review = None
        self.review_items = []
        self.last_export = None
        self._refreshing = False
        self._editor_split_sizes = [665, 220]
        self._last_workspace_index = 0
        self._origin_pending=False
        self.resize(1510, 960)
        self.setMinimumSize(1120, 720)
        # Apple-style appearance: follow the host by default, persist an explicit choice.
        self.settings = QSettings("ScientificPlotStudio", "SPS")
        preference = str(self.settings.value("appearance", "auto"))
        if preference not in ("auto", "light", "dark"):
            preference = "auto"
        self.appearance_preference = preference
        global _SYSTEM_APPEARANCE
        if _SYSTEM_APPEARANCE is None:
            _SYSTEM_APPEARANCE = system_mode(QApplication.instance())
        self.appearance = _SYSTEM_APPEARANCE if preference == "auto" else preference
        apply_theme(QApplication.instance(), self.appearance)
        self.publication_preferences={}
        from .local_paths import data_dir
        self.publication_settings=data_dir()/"publication-preferences.json"
        if self.publication_settings.is_file():
            try:self.publication_preferences=read_json(self.publication_settings)
            except ValueError:pass
        self.setWindowTitle("Scientific Plot Studio")
        self._build_menu()
        self._build_ui()
        self.refresh()

    @property
    def project(self):
        return self.session.project

    def guard(self, fn):
        try:
            return fn()
        except Exception as e:
            self.statusBar().showMessage(str(e), 15000)
            QMessageBox.warning(self, "SPS · 操作未完成", str(e))
            return None

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("文件")
        edit_menu = self.menuBar().addMenu("编辑")
        tools_menu = self.menuBar().addMenu("工具")
        toolbar = QToolBar("项目工具")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(17, 17))
        self.addToolBar(toolbar)
        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(2, 0, 18, 0)
        brand_layout.setSpacing(0)
        title = QLabel("Scientific Plot Studio")
        title.setObjectName("brand_title")
        subtitle = QLabel(f"科研绘图  ·  {__version__}")
        subtitle.setObjectName("brand_subtitle")
        brand_layout.addWidget(title)
        brand_layout.addWidget(subtitle)
        toolbar.addWidget(brand)
        toolbar.addSeparator()
        actions = [
            (file_menu, "新建", "Ctrl+N", self.new_project, "new"),
            (file_menu, "打开", "Ctrl+O", self.open_project, "open"),
            (file_menu, "保存", "Ctrl+S", self.save_project, "save"),
            (file_menu, "另存为", "Ctrl+Shift+S", lambda: self.save_project(True), "save_as"),
            (file_menu, "导入数据", "Ctrl+I", self.import_data, "import"),
            (edit_menu, "撤销", "Ctrl+Z", self.undo, "undo"),
            (edit_menu, "重做", "Ctrl+Shift+Z", self.redo, "redo"),
        ]
        self.actions = {}
        for menu, title, shortcut, handler, key in actions:
            action = QAction(icon("save" if key == "save_as" else key, "#4b4b50"), title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda checked=False, h=handler: h())
            action.setObjectName(key)
            action.setToolTip(f"{title}  ·  {action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)}")
            menu.addAction(action)
            if key != "save_as":
                if key in ("undo", "import"):
                    toolbar.addSeparator()
                toolbar.addAction(action)
            self.actions[key] = action
        for title, handler in [("期刊规范：轴与字体…", self.publication_dialog), ("批量导入并规范化…", self.batch_publication), ("合成数据演示", self.load_demo), ("Origin 兼容能力", self.show_bridge)]:
            tools_menu.addAction(title).triggered.connect(handler)
        for title, shortcut, handler in (("复制图形与完整数据", "Ctrl+Shift+C", self.copy_editable),
                                         ("粘贴 SPS 可编辑工程", "Ctrl+Shift+V", self.paste_editable)):
            item=edit_menu.addAction(title); item.setShortcut(QKeySequence(shortcut)); item.triggered.connect(handler)
        file_menu.addAction("导出可编辑 PPTX（纯折线）").triggered.connect(self.export_pptx)
        file_menu.addAction("从 SPS PPTX 恢复工程").triggered.connect(self.recover_pptx)
        file_menu.addAction("导出便携图形对象（.spsfig）…").triggered.connect(lambda:self.export_figure_object())
        file_menu.addAction("导出带 SPS 编辑入口的 Word / PPT…").triggered.connect(lambda:self.export_office_figure())
        file_menu.addAction("生成更新后的 Word / PPT 副本…").triggered.connect(lambda:self.refresh_office_figure())
        file_menu.addAction("导出链接资源包（SVG / PNG + 工程）…").triggered.connect(lambda:self.export_linked_assets())
        file_menu.addAction("更新当前对象的链接预览…").triggered.connect(lambda:self.refresh_linked_assets())
        office_copy=edit_menu.addAction("复制图像（本机保留完整工程）",self.copy_office_figure)
        office_copy.setShortcut(QKeySequence('Ctrl+Alt+C'))
        view_menu = self.menuBar().addMenu("视图")
        self.view_menu=view_menu
        self.inspector_action=QAction("显示属性面板",self);self.inspector_action.setCheckable(True);self.inspector_action.setChecked(True)
        self.inspector_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.data_panel_action=QAction("显示数据与操作记录",self);self.data_panel_action.setCheckable(True);self.data_panel_action.setChecked(True)
        self.data_panel_action.setShortcut(QKeySequence("Ctrl+J"))
        for action in (self.inspector_action,self.data_panel_action):
            view_menu.addAction(action);action.toggled.connect(lambda checked:self.workspace_changed(self.workspaces.currentIndex()))
        search=QAction("查找图形对象",self);search.setShortcut(QKeySequence("Ctrl+F"));search.triggered.connect(self.focus_project_filter)
        view_menu.addAction(search)
        view_menu.addSeparator()
        palette_action=QAction(icon("command","#4b4b50"),"命令面板…",self)
        palette_action.setShortcut(QKeySequence("Ctrl+K"));palette_action.triggered.connect(self.open_command_palette)
        shortcuts_action=QAction("键盘快捷键…",self);shortcuts_action.setShortcut(QKeySequence("Ctrl+/"))
        shortcuts_action.triggered.connect(self.show_shortcuts)
        self.sidebar_action=QAction("折叠侧栏",self);self.sidebar_action.setCheckable(True)
        self.sidebar_action.setShortcut(QKeySequence("Ctrl+Alt+S"))
        # The menu item is "折叠侧栏", so checked means hidden.
        self.sidebar_action.toggled.connect(lambda checked: self.set_sidebar_visible(not checked))
        for action in (palette_action,shortcuts_action,self.sidebar_action):
            view_menu.addAction(action)
        view_menu.addSeparator()
        appearance_menu=view_menu.addMenu("外观")
        self.appearance_group=QActionGroup(self);self.appearance_group.setExclusive(True)
        self.appearance_actions={}
        for key,title in (("auto","跟随系统"),("light","浅色"),("dark","深色")):
            action=QAction(title,self);action.setCheckable(True)
            action.setChecked(self.appearance_preference==key)
            action.triggered.connect(lambda checked=False,mode=key:self.set_appearance(mode))
            self.appearance_group.addAction(action);appearance_menu.addAction(action)
            self.appearance_actions[key]=action
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.palette_button=QToolButton();self.palette_button.setIcon(icon("search","#4b4b50"))
        self.palette_button.setToolTip("命令面板  ·  ⌘K")
        self.palette_button.setAccessibleName("命令面板")
        self.palette_button.clicked.connect(self.open_command_palette)
        toolbar.addWidget(self.palette_button)
        self.appearance_button=QToolButton()
        self.appearance_button.setToolTip("切换浅色 / 深色外观")
        self.appearance_button.setAccessibleName("切换外观")
        self.appearance_button.clicked.connect(self.toggle_appearance)
        toolbar.addWidget(self.appearance_button)
        self.sidebar_button=QToolButton();self.sidebar_button.setIcon(icon("sidebar","#4b4b50"))
        self.sidebar_button.setToolTip("折叠侧栏  ·  ⌥⌘S");self.sidebar_button.setCheckable(True)
        self.sidebar_button.setChecked(True);self.sidebar_button.setAccessibleName("折叠侧栏")
        self.sidebar_button.toggled.connect(self.set_sidebar_visible)
        toolbar.addWidget(self.sidebar_button)
        toolbar.addSeparator()
        self.publication_button=QToolButton()
        self.publication_button.setObjectName("toolbar_text")
        self.publication_button.setText("期刊规范")
        self.publication_button.setIcon(icon("axes",self.icon_color))
        self.publication_button.setIconSize(QSize(16,16))
        self.publication_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.publication_button.clicked.connect(self.publication_dialog)
        toolbar.addWidget(self.publication_button)
        self.templates_action = QAction(icon("template",self.icon_color), "模板库", self)
        self.templates_action.triggered.connect(lambda: self.workspaces.setCurrentIndex(self.template_index))
        toolbar.addAction(self.templates_action)
        self.export_action = QAction(icon("export",tokens(self.appearance)["accent"]), "导出", self)
        self.export_action.triggered.connect(lambda: self.workspaces.setCurrentIndex(self.export_index))
        toolbar.addAction(self.export_action)
        self._sync_appearance_button()

    @property
    def icon_color(self):
        return "#3c3c43" if self.appearance == "light" else "#d1d1d6"

    def _nav_icon(self, name):
        return icon(name, "#2c2c2e" if self.appearance == "light" else "#e5e5ea", 1.85)

    def _apply_icon_colors(self):
        """Icons are painted bitmaps, so they are re-rendered when appearance flips."""
        color = self.icon_color
        for key, action in getattr(self, "actions", {}).items():
            action.setIcon(icon("save" if key == "save_as" else key, color))
        for key, button in getattr(self, "nav_buttons", {}).items():
            button.setIcon(self._nav_icon(key))
        for name, button in (("search", getattr(self, "palette_button", None)),
                             ("sidebar", getattr(self, "sidebar_button", None)),
                             ("axes", getattr(self, "publication_button", None))):
            if button is not None:
                button.setIcon(icon(name, color))
        if hasattr(self, "templates_action"):
            self.templates_action.setIcon(icon("template", color))
        if hasattr(self, "export_action"):
            self.export_action.setIcon(icon("export", tokens(self.appearance)["accent"]))
        nav = getattr(self, "workspace_nav", None)
        labels = getattr(self, "_workspace_labels", [])
        if nav is not None:
            for index, (_, kind) in enumerate(labels):
                item = nav.item(index)
                if item is not None:
                    item.setIcon(icon(kind, color))
        if hasattr(self, "appearance_button"):
            self._sync_appearance_button()

    def _sync_appearance_button(self):
        dark=self.appearance=="dark"
        self.appearance_button.setIcon(icon("sun" if dark else "moon",self.icon_color))
        self.appearance_button.setToolTip("切换到浅色外观" if dark else "切换到深色外观")

    def set_appearance(self, preference):
        """Apply 跟随系统 / 浅色 / 深色 and remember the choice for next launch."""
        if preference not in ("auto","light","dark"):
            preference="auto"
        self.appearance_preference=preference
        self.settings.setValue("appearance",preference)
        mode=_SYSTEM_APPEARANCE if preference=="auto" else preference
        self.appearance=mode or "light"
        apply_theme(QApplication.instance(),self.appearance)
        for key,action in self.appearance_actions.items():
            action.setChecked(key==preference)
        self._apply_icon_colors()
        self.statusBar().showMessage("外观："+{"auto":"跟随系统","light":"浅色","dark":"深色"}[preference],6000)

    def toggle_appearance(self):
        self.set_appearance("light" if self.appearance=="dark" else "dark")

    def open_command_palette(self):
        CommandPalette(self._commands(),self).exec()

    def show_shortcuts(self):
        ShortcutsSheet(self).exec()

    def set_sidebar_visible(self, visible):
        if not hasattr(self,"project_sidebar"):return
        self.project_sidebar.setVisible(bool(visible))
        self.sidebar_button.blockSignals(True);self.sidebar_button.setChecked(bool(visible));self.sidebar_button.blockSignals(False)
        self.sidebar_action.blockSignals(True);self.sidebar_action.setChecked(not visible);self.sidebar_action.blockSignals(False)

    def toggle_sidebar(self):
        self.set_sidebar_visible(not self.project_sidebar.isVisible())

    def _commands(self):
        """One searchable registry behind ⌘K; every entry maps to an existing action."""
        commands=[]
        def add(title,run,subtitle="",shortcut="",icon_name="command",keywords="",group="操作"):
            commands.append(Command(title,run,subtitle,shortcut,icon_name,keywords,group))
        for key,title,group in (("new","新建工程","文件"),("open","打开工程或 Origin 文件","文件"),
                                ("save","保存工程","文件"),("import","导入数据","文件"),
                                ("undo","撤销","编辑"),("redo","重做","编辑")):
            action=self.actions.get(key)
            if action:
                native=action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
                add(title,action.trigger,"",native,key,key,group)
        add("导出格式与预检",lambda:self.workspaces.setCurrentIndex(self.export_index),"PNG / SVG / PDF / TIFF","","export","导出 输出 预检","导出")
        add("期刊规范：轴与字体",self.publication_dialog,"Nature / Elsevier 预设","","axes","期刊 字号 坐标轴 规范化","工具")
        add("批量导入并规范化",self.batch_publication,"多个 Origin 工程","","import","批量 导入","工具")
        add("命令面板",self.open_command_palette,"搜索命令与工作区","⌘K","search","spotlight 搜索","视图")
        add("键盘快捷键",self.show_shortcuts,"完整列表","⌘/","keyboard","快捷键 帮助","视图")
        add("切换外观",self.toggle_appearance,"浅色 / 深色","","moon","dark light 主题","视图")
        add("折叠侧栏",self.toggle_sidebar,"给画布更多空间","⌥⌘S","sidebar","侧栏 导航","视图")
        add("查找图形对象",self.focus_project_filter,"聚焦侧栏搜索框","⌘F","search","查找 过滤","编辑")
        add("复制图形与完整数据",self.copy_editable,"SPS 可编辑粘贴","⇧⌘C","data","剪贴板 复制","编辑")
        add("导出带 SPS 编辑入口的 Word / PPT",lambda:self.export_office_figure(),"双击可回到 SPS","","export","office word ppt","导出")
        add("复制图像（保留完整工程）",self.copy_office_figure,"粘贴到 Office","⌥⌘C","data","office 复制","编辑")
        for index,(title,kind) in enumerate([("图形编辑","chart"),("模板库","template"),("导出校验","export"),
                                             ("风格审查","review"),("Origin 样式","chart"),("AI 助手","review"),("数据与 Office","data")]):
            add(title,lambda checked=False,i=index:self.workspaces.setCurrentIndex(i),f"工作区 {index+1}",f"⌘{index+1}",kind,title,"工作区")
        figure=self.project.figure
        for series in figure.series:
            add(series.label,lambda checked=False,ident=series.id:self.select_object(ident),
                f"曲线 · {series.x} / {series.y}", "", "chart", f"{series.label} {series.x} {series.y}", "当前工程")
        for annotation in figure.annotations:
            add(annotation.text[:40],lambda checked=False,ident=annotation.id:self.select_object(ident),
                "文字注释", "", "text", annotation.text, "当前工程")
        for dataset in self.project.datasets:
            add(dataset.name,lambda checked=False,ident=dataset.id:self.select_object(ident),
                f"数据集 · {len(dataset.columns)} 列", "", "data", dataset.name, "当前工程")
        return commands

    def select_object(self, ident):
        """Used by ⌘K: jump to the editor and select a series, text or dataset."""
        self.workspaces.setCurrentIndex(self.editor_index)
        self.active_id = ident
        if any(dataset.id == ident for dataset in self.project.datasets):
            self.dataset_id = ident
        self.refresh()

    def _build_ui(self):
        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.setChildrenCollapsible(False)
        left = QWidget()
        left.setObjectName("project_sidebar")
        self.project_sidebar = left
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 10, 0, 8)
        left_layout.setSpacing(0)
        workspace_label = label("工作区")
        workspace_label.setObjectName("section_label")
        workspace_label.setContentsMargins(16, 2, 16, 6)
        left_layout.addWidget(workspace_label)
        self.workspace_nav=QListWidget();self.workspace_nav.setObjectName("workspace_nav")
        self.workspace_nav.setAccessibleName("工作区导航");self.workspace_nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.workspace_nav.setIconSize(QSize(17,17));self.workspace_nav.setFixedHeight(7*32+4)
        self.workspace_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.workspace_nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_layout.addWidget(self.workspace_nav)
        self.project_heading=label("当前工程")
        self.project_heading.setObjectName("section_label")
        self.project_heading.setContentsMargins(16, 16, 16, 6)
        left_layout.addWidget(self.project_heading)
        filter_wrap = QWidget()
        filter_layout = QHBoxLayout(filter_wrap)
        filter_layout.setContentsMargins(10, 0, 10, 8)
        self.project_filter = QLineEdit()
        self.project_filter.setObjectName("search_field")
        self.project_filter.setPlaceholderText("搜索曲线、数据或注释")
        self.project_filter.setClearButtonEnabled(True)
        self.project_filter.textChanged.connect(self.filter_project_tree)
        filter_layout.addWidget(self.project_filter)
        left_layout.addWidget(filter_wrap)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(85)
        self.tree.setAccessibleName("当前工程对象")
        self.tree.setObjectName("object_tree")
        self.tree.setIndentation(14)
        self.tree.itemSelectionChanged.connect(self.tree_selected)
        self.tree.itemChanged.connect(self.tree_visibility_changed)
        tree_wrap = QWidget()
        tree_layout = QVBoxLayout(tree_wrap)
        tree_layout.setContentsMargins(6, 0, 6, 0)
        tree_layout.addWidget(self.tree)
        left_layout.addWidget(tree_wrap, 1)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(8, 6, 8, 2)
        footer_layout.setSpacing(1)
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setObjectName("hairline")
        separator_wrap = QWidget()
        separator_layout = QVBoxLayout(separator_wrap)
        separator_layout.setContentsMargins(8, 0, 8, 6)
        separator_layout.addWidget(separator)
        left_layout.addWidget(separator_wrap)
        self.add_plot_button=button("添加曲线", self.add_plot)
        self.add_text_button=button("添加文字", self.add_annotation)
        self.remove_button=button("删除所选", self.remove_object)
        for widget in (self.add_plot_button,self.add_text_button,self.remove_button):
            widget.setProperty("variant","sidebar")
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
            footer_layout.addWidget(widget)
        self.add_plot_button.setProperty("accent","true")
        self.remove_button.setProperty("muted","true")

        left_layout.addWidget(footer)
        self.provenance = label("", True)
        self.provenance.setContentsMargins(16, 6, 12, 10)
        left_layout.addWidget(self.provenance)
        outer.addWidget(left)

        middle = QSplitter(Qt.Orientation.Vertical)
        self.middle_splitter = middle
        middle.setChildrenCollapsible(False)
        self.workspaces = QTabWidget()
        self.workspaces.setObjectName("workspaces")
        self.workspaces.setDocumentMode(True)
        self.workspaces.tabBar().hide()
        self._build_editor()
        self._build_templates()
        self._build_export()
        self._build_agent()
        self._build_origin_ai()
        middle.addWidget(self.workspaces)
        bottom = QTabWidget()
        self.bottom_panel = bottom
        bottom.setObjectName("bottom_tabs")
        bottom.setDocumentMode(True)
        bottom.setIconSize(QSize(14,14))
        self.data_table = QTableWidget()
        self.data_table.setObjectName("data_table")
        self.data_table.setAlternatingRowColors(True)
        self.data_table.itemChanged.connect(self.cell_changed)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        bottom.addTab(self.data_table, icon("data"), "数据表 · 工程副本")
        self.audit_text = QPlainTextEdit()
        self.audit_text.setReadOnly(True)
        bottom.addTab(self.audit_text, icon("review"), "操作记录")
        middle.addWidget(bottom)
        middle.setSizes([665, 220])
        outer.addWidget(middle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inspector = QWidget()
        inspector.setObjectName("inspector_surface")
        self.inspector_layout = QVBoxLayout(inspector)
        self.inspector_layout.setContentsMargins(14, 14, 14, 16)
        self.inspector_layout.setSpacing(10)
        self._build_inspector()
        scroll.setWidget(inspector)
        self.right_stack = QStackedWidget()
        self.right_stack.setMinimumWidth(300)
        self.right_stack.setMaximumWidth(380)
        self.right_stack.addWidget(scroll)
        export_scroll = QScrollArea()
        export_scroll.setWidgetResizable(True)
        export_scroll.setWidget(self.export_settings_panel)
        self.right_stack.addWidget(export_scroll)
        self.workspaces.currentChanged.connect(self.workspace_changed)
        outer.addWidget(self.right_stack)
        self.outer_splitter=outer
        left.setMinimumWidth(200);left.setMaximumWidth(268)
        outer.setSizes([232, 974, 304])
        outer.setStretchFactor(1, 1)
        self.setCentralWidget(outer)
        self.document_info = QLabel()
        self.statusBar().addPermanentWidget(self.document_info)
        self.statusBar().showMessage("就绪 · 所有编辑均保存在本地工程")
        self.reload_templates()
        self._build_workspace_navigation()
        self.workspace_changed(self.workspaces.currentIndex())
        # Scroll areas auto-fill their content from the OS palette; explicitly
        # style only their surfaces so labels and child controls remain native.
        for area in self.findChildren(QScrollArea):
            if area.property("no_surface"):
                continue
            style_scroll_surface(area)

    def _build_workspace_navigation(self):
        labels=[("图形编辑","chart"),("模板库","template"),("导出校验","export"),
                ("风格审查","review"),("Origin 样式","chart"),("AI 助手","review"),("数据与 Office","data")]
        self._workspace_labels = labels
        for index,(title,kind) in enumerate(labels):
            self.workspaces.setTabText(index,title)
            item=QListWidgetItem(icon(kind,self.icon_color),title);item.setSizeHint(QSize(196,32));self.workspace_nav.addItem(item)
            shortcut=QAction(title,self);shortcut.setShortcut(QKeySequence(f"Ctrl+{index+1}"))
            shortcut.triggered.connect(lambda checked=False,i=index:self.workspaces.setCurrentIndex(i));self.view_menu.addAction(shortcut)
            item.setToolTip(title+" · "+shortcut.shortcut().toString(QKeySequence.SequenceFormat.NativeText))
        self.workspace_nav.setCurrentRow(self.workspaces.currentIndex())
        self.workspace_nav.currentRowChanged.connect(self.workspaces.setCurrentIndex)
        self._apply_icon_colors()

    def workspace_changed(self, index):
        if not hasattr(self,"bottom_panel") or not hasattr(self,"right_stack"):return
        if self._last_workspace_index==self.editor_index and index!=self.editor_index and self.bottom_panel.isVisible():
            self._editor_split_sizes=self.middle_splitter.sizes()
        self.workspace_nav.blockSignals(True);self.workspace_nav.setCurrentRow(index);self.workspace_nav.blockSignals(False)
        editor=index==self.editor_index;inspector=index in (self.editor_index,self.export_index)
        self.right_stack.setCurrentIndex(1 if index==self.export_index else 0)
        self.right_stack.setVisible(inspector and self.inspector_action.isChecked())
        self.inspector_action.setEnabled(inspector);self.data_panel_action.setEnabled(editor)
        self.bottom_panel.setVisible(editor and self.data_panel_action.isChecked())
        for widget in (self.project_heading,self.project_filter,self.tree,self.add_plot_button,self.add_text_button,self.remove_button,self.provenance):
            widget.setVisible(editor)
        if editor and self.bottom_panel.isVisible() and self._last_workspace_index!=index:
            self.middle_splitter.setSizes(self._editor_split_sizes)
        self._last_workspace_index=index

    def filter_project_tree(self, query):
        if not hasattr(self, "tree"):
            return
        query = query.strip().casefold()

        def visit(item, inherited=False):
            matches = not query or query in item.text(0).casefold()
            visible_children = [visit(item.child(i), inherited or matches) for i in range(item.childCount())]
            visible = inherited or matches or any(visible_children)
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def focus_project_filter(self):
        self.workspaces.setCurrentIndex(self.editor_index)
        self.project_filter.setFocus()
        self.project_filter.selectAll()

    def reload_templates(self, selected_hash=None):
        self.template_panel.set_catalog(self.template_library.items(), selected_hash)
        self.template_panel.state.setToolTip("\n".join(self.template_library.errors))

    def capture_native_template(self):
        def run():
            if not self.project.figure.series:
                raise ValueError("请先添加至少一条曲线，再保存模板")
            dialog = CaptureTemplateDialog(self.project, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if not dialog.name.text().strip():
                raise ValueError("模板名称不能为空")
            template = dialog.template(self.project)
            self.template_library.add(template)
            self.reload_templates(template.fingerprint())
            self.workspaces.setCurrentIndex(self.template_index)
            self.statusBar().showMessage("模板已保存至个人库 · 不含原始数据数值", 12000)
        self.guard(run)

    def import_native_template(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "导入 SPS 原生模板", "", "SPS 模板 (*.sps-template.json)")
        if not path:
            return
        def run():
            template = templates.load(path)
            self.template_library.add(template)
            self.reload_templates(template.fingerprint())
            self.workspaces.setCurrentIndex(self.template_index)
            self.statusBar().showMessage("已导入原生模板 · 未修改当前图形", 10000)
        self.guard(run)

    def export_native_template(self, path=None):
        template = self.template_panel.selected_template()
        if template is None:
            return
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "导出原生模板", template.name + ".sps-template.json", "SPS 模板 (*.sps-template.json)")
        if path:
            if not str(path).endswith(".sps-template.json") and Path(path).suffix.lower() not in (".otp", ".otpu", ".oth"):
                path = str(path) + ".sps-template.json"
            self.guard(lambda: templates.save(template, path))

    def bind_native_template(self):
        def run():
            template = self.template_panel.selected_template()
            if template is None:
                raise ValueError("请先选择模板")
            if not self.project.datasets:
                raise ValueError("请先导入一组数据")
            dialog = TemplateBindingDialog(self.project, template, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.agent_input.setPlainText(json.dumps([dialog.operation()], ensure_ascii=False, indent=2))
            self.workspaces.setCurrentIndex(self.agent_index)
            self.preview_agent()
        self.guard(run)

    def _build_editor(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 18, 22, 14)
        layout.setSpacing(9)
        header = QHBoxLayout()
        header.setSpacing(12)
        title_block = QVBoxLayout()
        title_block.setSpacing(1)
        heading = label("图形编辑器")
        heading.setObjectName("workspace_title")
        title_block.addWidget(heading)
        self.page_info = label("", True)
        self.page_info.setWordWrap(False)
        title_block.addWidget(self.page_info)
        header.addLayout(title_block)
        header.addStretch()
        self.zoom_control = QFrame()
        self.zoom_control.setObjectName("segmented")
        zoom_layout = QHBoxLayout(self.zoom_control)
        zoom_layout.setContentsMargins(2, 2, 2, 2)
        zoom_layout.setSpacing(2)
        self.zoom_buttons = {}
        self._zoom_group = QButtonGroup(self)
        self._zoom_group.setExclusive(True)
        for key, text, tip in (("fit", "适应", "整页适应窗口"), (1.0, "100%", "按物理尺寸显示"),
                               (1.5, "150%", "放大查看细节"), (2.0, "200%", "放大查看细节")):
            segment = QToolButton()
            segment.setText(text)
            segment.setCheckable(True)
            segment.setToolTip(tip + " · 仅影响查看，不改变导出尺寸")
            segment.clicked.connect(lambda checked=False, value=key: self.set_zoom(value))
            zoom_layout.addWidget(segment)
            self._zoom_group.addButton(segment)
            self.zoom_buttons[key] = segment
        self.zoom_buttons["fit"].setChecked(True)
        header.addWidget(self.zoom_control)
        layout.addLayout(header)
        self.graph_tabs=QTabBar();self.graph_tabs.setObjectName("graph_tabs")
        self.graph_tabs.setAccessibleName('工程图页')
        self.graph_tabs.setExpanding(False);self.graph_tabs.setUsesScrollButtons(True)
        self.graph_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.graph_tabs.currentChanged.connect(self.select_graph_page);self.graph_tabs.hide();layout.addWidget(self.graph_tabs)
        context_row=QHBoxLayout();context_row.setSpacing(2)
        self.nav_buttons={}
        for key,icon_name,tip,checkable in (("home","home","适应画布",False),("back","back","上一视图",False),
                                            ("forward","forward","下一视图",False),("pan","pan","平移",True),
                                            ("zoom","zoom","框选缩放",True)):
            control=QToolButton();control.setObjectName("nav_button")
            control.setIcon(self._nav_icon(icon_name))
            control.setIconSize(QSize(16,16))
            control.setToolTip(tip+" · 仅改变查看范围");control.setCheckable(checkable)
            control.setFixedSize(26,24);control.setAccessibleName(tip)
            control.clicked.connect(lambda checked=False,name=key:self._navigate(name))
            context_row.addWidget(control);self.nav_buttons[key]=control
        context_row.addSpacing(10)
        self.layer_combo=QComboBox();self.layer_combo.setAccessibleName('当前图层')
        self.layer_combo.setMinimumContentsLength(8);self.layer_combo.currentIndexChanged.connect(self.select_graph_layer)
        context_row.addWidget(self.layer_combo)
        self.import_summary=label('',True);context_row.addWidget(self.import_summary,1)
        self.import_details_button=button('导入详情',self.show_import_details);context_row.addWidget(self.import_details_button)
        layout.addLayout(context_row)
        self.origin_progress=QProgressBar();self.origin_progress.setRange(0,0);self.origin_progress.setTextVisible(False)
        self.origin_progress.setFixedHeight(4);self.origin_progress.hide();layout.addWidget(self.origin_progress)
        self.canvas = FigureCanvasQTAgg(Figure(layout="constrained"))
        self.canvas.setObjectName("plot_canvas")
        self.canvas.setMinimumSize(160, 100)
        self.canvas.mpl_connect("pick_event", self.pick_object)
        self.navigation = ViewToolbar(self.canvas, panel)
        self.navigation.setIconSize(QSize(16, 16))
        self.navigation.hide()
        self.page_frame = FigurePage(self.canvas)
        self.canvas_scroll = QScrollArea()
        self.canvas_scroll.setObjectName("canvas_scroll")
        self.canvas_scroll.setProperty("no_surface", True)
        self.canvas_scroll.setWidgetResizable(True)
        self.canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.canvas_scroll.setWidget(self.page_frame)
        layout.addWidget(self.canvas_scroll, 1)
        layout.addWidget(HelpDisclosure("在图中或对象树选择元素，右侧编辑属性。平移/缩放仅供查看；要保存轴范围，请在坐标轴页设置。", "画布操作"))
        self.editor_index = self.workspaces.addTab(panel, icon("chart"), "图形编辑")

    def _navigate(self, name):
        handler = getattr(self.navigation, name, None)
        if handler is None:
            return
        handler()
        mode = getattr(getattr(self.navigation, "mode", None), "name", "").lower()
        for key in ("pan", "zoom"):
            button = self.nav_buttons.get(key)
            if button is not None:
                button.setChecked(mode == key)

    def set_zoom(self, zoom):
        """View-only scale; None / "fit" returns to the whole-page view."""
        value = None if zoom == "fit" else float(zoom)
        self.page_frame.set_zoom(value)
        for key, button in self.zoom_buttons.items():
            selected = (key == "fit" and value is None) or (key != "fit" and value == key)
            button.setChecked(selected)
        self._update_page_info()

    def _update_page_info(self):
        figure = self.project.figure
        self.page_info.setText(f"{figure.width_mm:g} × {figure.height_mm:g} mm  ·  {self.page_frame.zoom_text()}")

    def _build_templates(self):
        self.template_panel = TemplateLibraryPanel(CheckerPreview)
        self.template_panel.captureRequested.connect(self.capture_native_template)
        self.template_panel.importRequested.connect(self.import_native_template)
        self.template_panel.exportRequested.connect(self.export_native_template)
        self.template_panel.applyRequested.connect(self.bind_native_template)
        self.template_index = self.workspaces.addTab(self.template_panel, icon("template"), "模板库")

    def _build_export(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 14)
        heading = label("导出与校验")
        heading.setObjectName("workspace_title")
        layout.addWidget(heading)
        layout.addWidget(label("本机真实预览 · 跨平台显示尚未验收", True))
        background_row = QHBoxLayout()
        background_row.addWidget(label("预览背景"))
        self.preview_background = combo(["透明棋盘", "白色", "黑色"])
        self.preview_background.setObjectName("preview_background")
        background_row.addWidget(self.preview_background)
        background_row.addWidget(label("仅影响预览，不修改导出背景", True), 1)
        layout.addLayout(background_row)
        previews = QHBoxLayout()
        self.export_preview = CheckerPreview()
        self.export_preview.empty_text = "PNG · 请先预检"
        self.svg_preview = CheckerPreview()
        self.svg_preview.empty_text = "SVG · 导出后显示实际文件"
        for title, widget in [("PNG · 本机栅格预览", self.export_preview), ("SVG · 本机 Qt 阅读器", self.svg_preview)]:
            column = QVBoxLayout()
            column.addWidget(label(title))
            column.addWidget(widget, 1)
            previews.addLayout(column, 1)
        self.preview_background.currentIndexChanged.connect(self.set_preview_background)
        layout.addLayout(previews, 1)
        self.export_settings_panel = QWidget()
        self.export_settings_panel.setObjectName("inspector_surface")
        settings_layout = QVBoxLayout(self.export_settings_panel)
        settings_layout.setContentsMargins(14, 14, 14, 16)
        settings_layout.setSpacing(10)
        settings_group = QGroupBox("文件与分辨率")
        form = QFormLayout(settings_group)
        self.export_dir = QLineEdit(str(Path.cwd() / "exports"))
        self.export_stem = QLineEdit("figure")
        self.export_dpi = QSpinBox()
        self.export_dpi.setRange(72, 1200)
        self.export_dpi.setValue(300)
        self.transparent = QCheckBox("保留透明背景")
        self.transparent.setChecked(True)
        form.addRow("目录", self.export_dir)
        form.addRow("文件名", self.export_stem)
        form.addRow("DPI", self.export_dpi)
        form.addRow(self.transparent)
        form.addRow(button("选择输出目录", self.choose_export_dir))
        settings_layout.addWidget(settings_group)
        format_group = QGroupBox("导出格式")
        format_layout = QVBoxLayout(format_group)
        self.format_checks = {}
        for fmt in ("png", "svg", "pdf", "tiff"):
            check = QCheckBox(fmt.upper())
            check.setChecked(True)
            format_layout.addWidget(check)
            self.format_checks[fmt] = check
        settings_layout.addWidget(format_group)
        self.export_size_info = label("", True)
        settings_layout.addWidget(self.export_size_info)
        settings_layout.addWidget(button("修改画布尺寸", self.go_to_canvas))
        settings_layout.addWidget(HelpDisclosure("SVG文字转路径，PDF嵌入TrueType字体；PNG/TIFF可保留透明通道。字体缺失或裁切失败时会阻止导出。", "字体与透明度"))
        settings_layout.addWidget(button("预检与预览", self.run_preflight, name="preflight"))
        settings_layout.addWidget(button("导出并校验", self.do_export, True, "export"))
        settings_layout.addWidget(HelpDisclosure("本机文件校验不等于所有平台或Office排版一致。Origin数据请到数据与Office；完整Origin工程写回未实现。", "兼容范围"))
        settings_layout.addStretch()
        self.export_report = QPlainTextEdit()
        self.export_report.setReadOnly(True)
        self.export_report.setMaximumHeight(72)
        self.export_checks = QTableWidget(5, 3)
        self.export_checks.setHorizontalHeaderLabels(["检查", "状态", "范围 / 依据"])
        self.export_checks.verticalHeader().hide()
        self.export_checks.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.export_checks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.export_checks.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.export_checks.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.export_checks.setFixedHeight(185)
        layout.addWidget(self.export_checks)
        layout.addWidget(self.export_report)
        self.export_index = self.workspaces.addTab(panel, icon("export"), "导出与校验")
        for field in (self.export_dir, self.export_stem):
            field.textChanged.connect(self.invalidate_export)
        self.export_dpi.valueChanged.connect(self.invalidate_export)
        self.transparent.toggled.connect(self.invalidate_export)
        for check in self.format_checks.values():
            check.toggled.connect(self.invalidate_export)

    def _build_agent(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 18, 22, 14)
        layout.setSpacing(10)
        heading = label("风格与操作审查")
        heading.setObjectName("workspace_title")
        layout.addWidget(heading)
        layout.addWidget(label("比较预览 → 勾选属性 → 应用修改", True))
        self.planner_summary = label("", True)
        self.planner_summary.hide()
        layout.addWidget(self.planner_summary)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for text, handler in (("保存当前风格", self.extract_style), ("载入风格", self.load_style),
                              ("从工程提取风格", self.style_from_file)):
            buttons.addWidget(button(text, handler))
        buttons.addStretch()
        layout.addLayout(buttons)
        preview_row = QHBoxLayout()
        self.before_preview = AspectPreview("载入风格后显示当前图形")
        self.after_preview = AspectPreview("审查后显示所选修改")
        for title, w in [("修改前", self.before_preview), ("修改后 · 仅所选项", self.after_preview)]:
            col = QVBoxLayout()
            col.addWidget(label(title))
            w.setMinimumSize(180, 150)
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.setObjectName("preview_card")
            col.addWidget(w, 1)
            preview_row.addLayout(col, 1)
        layout.addLayout(preview_row, 2)
        self.review_summary = label("尚无有效审查；载入风格或预览操作计划。", True)
        layout.addWidget(self.review_summary)
        self.review_table = QTableWidget(0, 5)
        self.review_table.setObjectName("review_table")
        self.review_table.setHorizontalHeaderLabels(["应用", "属性", "当前", "建议", "影响"])
        self.review_table.verticalHeader().hide()
        self.review_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.review_table.setAlternatingRowColors(True)
        self.review_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.review_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.review_table.setMinimumHeight(130)
        self.review_table.itemChanged.connect(self.review_selection_changed)
        layout.addWidget(self.review_table, 2)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(button("预览操作计划", self.preview_agent, name="review"))
        self.apply_review_button = button("应用所选修改", self.apply_agent, True, "apply_review")
        self.apply_review_button.setEnabled(False)
        actions.addWidget(self.apply_review_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.agent_advanced = QWidget()
        advanced_layout = QHBoxLayout(self.agent_advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.agent_input = QPlainTextEdit()
        self.agent_input.setObjectName("agent_input");self.agent_input.setProperty("code",True)
        self.agent_input.setPlainText(json.dumps([{"op": "set_figure", "changes": {"grid": True, "font_size": 11}}], indent=2))
        self.agent_input.textChanged.connect(self.invalidate_review)
        self.agent_diff = QPlainTextEdit();self.agent_diff.setProperty("code",True)
        for editor in (self.agent_input,self.agent_diff):editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.agent_diff.setReadOnly(True)
        advanced_layout.addWidget(self.agent_input)
        advanced_layout.addWidget(self.agent_diff)
        self.agent_advanced.setMaximumHeight(155)
        self.agent_advanced.hide()
        toggle = QPushButton("高级：操作 JSON 与审查摘要")
        toggle.setCheckable(True)
        toggle.setProperty("variant","plain")
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.toggled.connect(self.agent_advanced.setVisible)
        layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.agent_advanced)
        self.agent_index = self.workspaces.addTab(panel, icon("review"), "风格与审查")

    def _build_origin_ai(self):
        settings = self.template_library.directory.parent
        self.origin_panel = OriginPanel(settings / "origin-reader.json", self)
        origin_scroll = QScrollArea()
        origin_scroll.setWidgetResizable(True)
        origin_scroll.setWidget(self.origin_panel)
        self.origin_index = self.workspaces.addTab(origin_scroll, icon("chart"), "Origin 分析")
        self.ai_panel = AIPanel(lambda: self.project, settings / "ai-config.json", self)
        ai_scroll = QScrollArea()
        ai_scroll.setWidgetResizable(True)
        ai_scroll.setWidget(self.ai_panel)
        self.ai_index = self.workspaces.addTab(ai_scroll, icon("review"), "AI 助手")
        self.origin_panel.styleRequested.connect(self.propose_origin_style)
        self.origin_panel.templateRequested.connect(self.store_origin_template)
        self.origin_panel.referenceSelected.connect(self.ai_panel.set_reference)
        self.origin_panel.observationsSelected.connect(self.ai_panel.set_observations)
        self.ai_panel.planReady.connect(self.review_ai_plan)
        self.office_panel = OfficePanel(self)
        office_scroll=QScrollArea(); office_scroll.setWidgetResizable(True); office_scroll.setWidget(self.office_panel)
        self.office_index=self.workspaces.addTab(office_scroll,icon('import'),'Origin 数据 / Office')
        self.office_panel.projectReady.connect(self.accept_recovered_project)
        self.office_panel.copyRequested.connect(self.copy_editable)
        self.office_panel.pasteRequested.connect(self.paste_editable)
        self.office_panel.exportRequested.connect(self.export_pptx)
        self.office_panel.recoverRequested.connect(self.recover_pptx)
        self.office_panel.importRequested.connect(self.open_project)
        self.office_panel.busyChanged.connect(self.origin_busy_changed)

    def origin_busy_changed(self,busy):
        self.origin_progress.setVisible(busy and self._origin_pending)
        if not busy and self._origin_pending:
            self._origin_pending=False
            self.import_summary.setText('读取未完成 · '+self.office_panel.status.text())
            self.import_summary.show()

    def select_graph_page(self,index):
        if self._refreshing or not self.project.pages or index<0:return
        self.flush_tree_visibility();self.project.select_context(index,0)
        self.active_id=None;self.refresh()

    def select_graph_layer(self,index):
        if self._refreshing or not self.project.pages or index<0:return
        self.flush_tree_visibility();self.project.select_context(self.project.context[0],index)
        self.active_id=None;self.refresh()

    def refresh_graph_context(self):
        p=self.project
        self.graph_tabs.blockSignals(True);self.layer_combo.blockSignals(True)
        try:
            wanted=[page.name for page in p.pages]
            if [self.graph_tabs.tabText(i)for i in range(self.graph_tabs.count())]!=wanted:
                while self.graph_tabs.count():self.graph_tabs.removeTab(0)
                for i,page in enumerate(p.pages):
                    n=self.graph_tabs.addTab(page.name);self.graph_tabs.setTabToolTip(n,f'源图序号 {page.source_index+1} · {len(page.layers)} 图层')
            self.graph_tabs.setVisible(bool(p.pages));self.layer_combo.clear()
            self.layer_combo.setVisible(bool(p.pages));self.import_details_button.setVisible(bool(p.pages))
            self.import_summary.setVisible(bool(p.pages)or self._origin_pending)
            if p.pages:
                pi,li=p.context;self.graph_tabs.setCurrentIndex(pi)
                for layer in p.pages[pi].layers:self.layer_combo.addItem('图层 '+layer.name if layer.name.isdigit()else layer.name)
                self.layer_combo.setCurrentIndex(li)
                bindings=p.origin.get('bindings',[]);bound=sum(b.get('status')=='bound'for b in bindings)
                total=sum(len(page.layers)for page in p.pages)
                self.import_summary.setText(f'{len(p.pages)} 图页 · {total} 图层 · {bound}/{len(bindings)} 曲线绑定 · 部分格式恢复'if p.origin else f'{len(p.pages)} 图页 · {total} 图层')
                current=p.pages[pi].issues+p.pages[pi].layers[li].issues
                self.import_summary.setToolTip('\n'.join(current))
        finally:self.graph_tabs.blockSignals(False);self.layer_combo.blockSignals(False)

    def show_import_details(self):
        p=self.project;lines=list(p.origin.get('issues',[]))
        for i,page in enumerate(p.pages,1):
            lines.append(f'{i}. {page.name} · {len(page.layers)} 图层')
            lines.extend('  '+issue for issue in page.issues)
            for layer in page.layers:
                lines.append(f'  {layer.name} · {len(layer.figure.series)} 可编辑曲线')
                lines.extend('    '+issue for issue in layer.issues)
        lines+=['','曲线引用（源记录顺序）：']
        for b in p.origin.get('bindings',[]):
            prefix=f"图{b['page']+1}/层{b['layer']+1}/曲线{b['curve']+1}"
            lines.append(f"{prefix}: X={b['x']} → Y={b['y']}"if b['status']=='bound'else prefix+': '+b.get('reason','未解析'))
        lines+=['','原始读取结果随SPS工程保留；当前结果不是Origin像素保真验收。',
                '图页遵循文件窗口记录顺序；项目浏览器自定义文件夹排序尚未独立校准。']
        dialog=QDialog(self);dialog.setWindowTitle('Origin 导入详情');dialog.resize(820,620)
        layout=QVBoxLayout(dialog);view=QPlainTextEdit();view.setReadOnly(True);view.setPlainText('\n'.join(lines));layout.addWidget(view)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);close.rejected.connect(dialog.reject);layout.addWidget(close)
        dialog.exec()

    def open_origin(self,path):
        if self.office_panel.busy:
            self.statusBar().showMessage('上一项读取仍在执行，请等待结果。',8000);return
        if not self.may_discard():return
        from .origin_graphs import read_project
        panel=self.office_panel;panel.source.setText(str(path))
        generation=panel.input_generation;base=self.project.fingerprint()
        self._origin_pending=True;self.workspaces.setCurrentIndex(self.editor_index)
        self.import_summary.setText('正在读取Origin数据、图页和曲线引用…');self.import_summary.show()
        self.origin_progress.show()
        probe=panel.probe.text().strip();decoder=panel.decoder.text().strip()
        def done(result):
            self._origin_pending=False;self.origin_progress.hide()
            if generation!=panel.input_generation or self.project.fingerprint()!=base:
                self.import_summary.setText('读取期间工程或来源已变化，未覆盖当前编辑。');return
            panel.set_recovery(result['recovery'])
            if result['project']is None:
                self.workspaces.setCurrentIndex(self.office_index)
                panel.status.setText('原图未自动恢复：'+result['error']);return
            imported=result['project']
            if self.publication_preferences.get('enabled'):
                from .publication import operation,PROFILES
                try:
                    normalized=Session(imported.clone())
                    opts={k:self.publication_preferences[k]for k in('profile','size','font')}
                    normalized.execute([operation(**opts,scope='all')],actor='publication_auto_import')
                    imported=normalized.project
                except Exception as error:
                    imported.audit.append({'kind':'publication_auto_failed','error':str(error)})
                    QMessageBox.warning(self,'期刊规范未应用，已保留原图',str(error))
            self.replace_project(imported,check_layout=False)
            self.workspaces.setCurrentIndex(self.editor_index)
            self.statusBar().showMessage('Origin图页已按源名和记录顺序载入 · 未支持格式见“导入详情”',15000)
        panel.work(lambda:read_project(path,probe or None,decoder or None),done)

    def accept_recovered_project(self, project):
        if self.may_discard():
            def run():
                preflight(project,100)
                self.replace_project(project)
                self.workspaces.setCurrentIndex(0)
            self.guard(run)

    def copy_editable(self):
        def run():
            from .transfer import mime_data
            QApplication.clipboard().setMimeData(mime_data(self.project))
            self.statusBar().showMessage('已复制完整工程和原数据；SPS 可编辑粘贴，其他应用通常仅接收图像。',12000)
        self.guard(run)

    def paste_editable(self):
        def run():
            from .transfer import MIME,decode
            from . import figure_object as figure
            data=QApplication.clipboard().mimeData()
            if data and data.hasFormat(figure.MIME):
                info=figure.unpack(bytes(data.data(figure.MIME)))
                if self.may_discard():self.replace_project(info['project'],check_layout=False)
                return
            if not data or not data.hasFormat(MIME):
                self.workspaces.setCurrentIndex(self.office_index)
                raise ValueError('剪贴板没有 SPS 工程。Origin/Office 原始 OLE 剪贴板尚未支持；请保存 PPTX 后在复制与 PPT 页恢复。')
            self.accept_recovered_project(decode(bytes(data.data(MIME))))
        self.guard(run)

    def export_pptx(self, path=None):
        if not path:
            path,_=QFileDialog.getSaveFileName(self,'导出原生可编辑折线图','figure.pptx','PowerPoint (*.pptx)')
        if path:
            def run():
                from .pptx_io import export
                report=export(self.project,path)
                self.statusBar().showMessage('PPTX 已保存：可在 PowerPoint 编辑数据；Office 排版可能不同，完整 SPS 工程同时保留。',15000)
                return report
            return self.guard(run)

    def recover_pptx(self, path=None):
        if not path:
            path,_=QFileDialog.getOpenFileName(self,'恢复 SPS 导出的 PPTX','','PowerPoint (*.pptx)')
        if path:
            def run():
                from .pptx_io import recover
                self.accept_recovered_project(recover(path))
            self.guard(run)

    def propose_origin_style(self, style):
        self.propose_style(style)
        self.planner_summary.setText(f"Origin 部分风格：源 {len(style['series'])} 条 → 目标 {len(self.project.figure.series)} 条，按顺序循环映射。"
                                     "仅迁移可识别格式；线宽/虚线为近似对应，缺失项保留。")
        self.planner_summary.show()
        self.workspaces.setCurrentIndex(self.agent_index)

    def store_origin_template(self, template):
        def run():
            self.template_library.add(template)
            self.reload_templates(template.fingerprint())
            self.workspaces.setCurrentIndex(self.template_index)
            self.statusBar().showMessage("所选层部分模板已保存；未映射项见模板说明，绑定时需确认", 12000)
        self.guard(run)

    def review_ai_plan(self, plan):
        def run():
            if plan["base_hash"] != self.project.fingerprint():
                raise ValueError("AI 建议对应的工程已变化，请重新生成")
            if not plan["review"]:
                return
            self.agent_input.setPlainText(json.dumps(plan["review"]["operations"], ensure_ascii=False, indent=2))
            self.preview_agent()
            self.planner_summary.setText(plan["summary"] + ("\n" + "；".join(plan["warnings"]) if plan["warnings"] else ""))
            self.planner_summary.show()
            self.workspaces.setCurrentIndex(self.agent_index)
        self.guard(run)

    def _build_inspector(self):
        inspector_title = label("属性")
        inspector_title.setObjectName("section_label")
        self.inspector_layout.addWidget(inspector_title)
        self.property_tabs = QTabWidget()
        self.property_tabs.setObjectName("property_tabs")
        self.property_tabs.setDocumentMode(True)
        self.property_tabs.setIconSize(QSize(14,14))
        self.property_tabs.tabBar().setExpanding(True)
        self.property_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        pages = []
        for name in ("曲线", "坐标轴", "画布", "文本", "图例"):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 10, 0, 0)
            layout.setSpacing(10)
            self.property_tabs.addTab(page, name)
            pages.append(layout)
        self.inspector_layout.addWidget(self.property_tabs)
        self.fig_fields = {}
        canvas_group = QGroupBox("画布与字体")
        canvas_form = QFormLayout(canvas_group)
        axes_group = QGroupBox("坐标与显示")
        axes_form = QFormLayout(axes_group)
        for form in (canvas_form, axes_form):
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(8)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, title, form in [("title", "标题", canvas_form), ("xlabel", "X 轴标签", axes_form),
                                 ("ylabel", "Y 轴标签", axes_form)]:
            w = QLineEdit()
            self.fig_fields[key] = w
            form.addRow(title, w)
        self.fig_fields["font"] = self._font_combo()
        canvas_form.insertRow(1, "字体", self.fig_fields["font"])
        for key, title, low, high, form in [("font_size", "字号 pt", 5, 48, canvas_form),
                                           ("width_mm", "宽度 mm", 40, 600, canvas_form),
                                           ("height_mm", "高度 mm", 40, 600, canvas_form),
                                           ("axis_width", "轴线宽 pt", .1, 5, axes_form)]:
            w = spin(10, low, high, .1 if key == "axis_width" else 1)
            self.fig_fields[key] = w
            form.addRow(title, w)
        for key, title in [("xscale", "X 比例"), ("yscale", "Y 比例")]:
            w = enum_combo([("线性", "linear"), ("对数", "log")])
            self.fig_fields[key] = w
            axes_form.addRow(title, w)
        for key, title in [("xlim", "X 最小,最大"), ("ylim", "Y 最小,最大")]:
            w = QLineEdit()
            w.setPlaceholderText("auto / 0, 100")
            self.fig_fields[key] = w
            axes_form.addRow(title, w)
        self.fig_fields["tick_direction"] = enum_combo([("朝内", "in"), ("朝外", "out"), ("内外", "inout")])
        axes_form.addRow("刻度方向", self.fig_fields["tick_direction"])
        for key, title in [("grid", "显示网格")]:
            w = QCheckBox(title)
            self.fig_fields[key] = w
            axes_form.addRow(w)
        axes_form.addRow(button("四边轴设置…", self.edit_axis_sides, icon_name="axes"))
        for key, title in [("x_major_step", "X 主刻度间距"), ("y_major_step", "Y 主刻度间距")]:
            w = QLineEdit(); w.setPlaceholderText("auto / 正数（仅线性轴）")
            self.fig_fields[key] = w; axes_form.addRow(title, w)
        self.fig_fields["minor_divisions"] = QSpinBox(); self.fig_fields["minor_divisions"].setRange(0, 10)
        self.fig_fields["minor_divisions"].setToolTip("每个主刻度间隔内的次刻度数；0关闭，仅适用于线性轴")
        axes_form.addRow("每段次刻度数", self.fig_fields["minor_divisions"])
        legend_group = QGroupBox("图例位置与显示"); legend_form = QFormLayout(legend_group)
        legend_form.setContentsMargins(0, 0, 0, 0); legend_form.setVerticalSpacing(8)
        legend_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key,title in [("legend", "显示图例"), ("legend_frame", "显示图例边框")]:
            self.fig_fields[key] = QCheckBox(title); legend_form.addRow(self.fig_fields[key])
        self.fig_fields["legend_location"] = enum_combo([
            ("自动避让", "best"), ("右上", "upper right"), ("左上", "upper left"),
            ("右下", "lower right"), ("左下", "lower left"), ("上方居中", "upper center"),
            ("下方居中", "lower center"), ("左侧居中", "center left"), ("右侧居中", "center right"), ("中心", "center")])
        legend_form.addRow("位置", self.fig_fields["legend_location"])
        for key,title,form in [('xlabel_size','X标签字号 pt',axes_form),('ylabel_size','Y标签字号 pt',axes_form),
                               ('tick_size','刻度字号 pt',axes_form),('legend_size','图例字号 pt',legend_form)]:
            field=spin(0,0,96,1);field.setSpecialValueText('跟随通用字号')
            self.fig_fields[key]=field;form.addRow(title,field)

        legend_form.addRow(HelpDisclosure("图例文字来自各曲线名称；在曲线页修改名称。此处只调整图例显示。", "编辑图例文字"))
        legend_form.addRow(button("应用图例设置", self.apply_figure, True, "apply_legend"))
        pages[4].addWidget(legend_group)
        canvas_form.addRow(HelpDisclosure("毫米尺寸用于最终导出；编辑区缩放不改变导出尺寸。", "画布尺寸"))
        canvas_form.addRow(button("应用画布设置", self.apply_figure, True, "apply_figure"))
        axes_form.addRow(button("应用坐标设置", self.apply_figure, True, "apply_axes"))
        pages[1].addWidget(axes_group)
        pages[2].addWidget(canvas_group)
        self.series_group = QGroupBox("曲线类型与样式")
        form = QFormLayout(self.series_group)
        form.setContentsMargins(0, 0, 0, 0); form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.series_source = label("", True)
        form.addRow(self.series_source)
        self.series_fields = {"label": QLineEdit(), "kind": enum_combo(PLOT_TYPES),
                              "color": ColorField(), "width": spin(1.6, .1, 10, .1),
                              "marker": enum_combo([("无", "none"), ("圆形", "o"), ("方形", "s"), ("三角", "^"), ("菱形", "D"), ("加号", "+"), ("叉号", "x"), ("点", ".")]),
                              "marker_size": spin(4, 1, 25, .5), "line_style": enum_combo([("实线", "-"), ("虚线", "--"), ("点线", ":"), ("点划线", "-.")]),
                              "alpha": spin(100, 1, 100, 5), "visible": QCheckBox("显示曲线"), "y_error": QLineEdit()}
        self.series_fields["alpha"].setSuffix(" %")
        titles = {"label": "图例名称", "kind": "图形类型", "color": "颜色", "width": "线宽 pt", "marker": "符号",
                  "marker_size": "符号大小 pt", "line_style": "线型", "alpha": "不透明度", "visible": "显示", "y_error": "Y 误差列"}
        for key, w in self.series_fields.items():
            form.addRow(titles[key], w)
        self.batch_all = QCheckBox("将样式应用到所有曲线")
        form.addRow(self.batch_all)
        form.addRow(HelpDisclosure("批量只改颜色、线宽、线型与符号，不改标签、数据或误差定义。", "批量设置范围"))
        form.addRow(button("应用曲线设置", self.apply_series, True, "apply_series"))
        pages[0].addWidget(self.series_group)
        pages[0].addWidget(HelpDisclosure("点选左侧对象树或图中的曲线以编辑；复选框控制显隐。", "如何选择曲线"))
        self.annotation_group = QGroupBox("文字注释")
        form = QFormLayout(self.annotation_group)
        form.setContentsMargins(0, 0, 0, 0); form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.annotation_fields = {"text": QLineEdit(), "x": spin(.05, 0, 1, .05), "y": spin(.95, 0, 1, .05),
                                  "size": spin(11, 5, 48), "color": ColorField("#263841")}
        for key, title in [("text", "内容"), ("x", "位置 X"), ("y", "位置 Y"), ("size", "字号 pt"), ("color", "颜色")]:
            form.addRow(title, self.annotation_fields[key])
        form.addRow(HelpDisclosure("位置相对坐标区，范围0–1；超出画布时会拒绝应用或导出。", "文字位置"))
        form.addRow(button("应用文字设置", self.apply_annotation))
        pages[3].addWidget(self.annotation_group)
        pages[3].addWidget(label("选择或添加文字注释后编辑。", True))
        for page in pages:
            page.addStretch()
        self.inspector_layout.addStretch()

    def _font_combo(self):
        """Installed families, journal staples first. Export still refuses missing glyphs."""
        combo = QComboBox()
        combo.setToolTip("图形内字体；导出时缺字会明确报错，不做静默替换")
        # Hundreds of installed families must not dictate the panel width.
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.setMaxVisibleItems(18)
        families = set(QFontDatabase.families())
        curated = ["Arial", "Helvetica", "Helvetica Neue", "Times New Roman",
                   "Source Han Sans SC", "Noto Sans CJK SC", "PingFang SC", "Songti SC", "DejaVu Sans"]
        ordered = [name for name in curated if name in families]
        for name in ordered:
            combo.addItem(name, name)
        rest = sorted(name for name in families if name not in ordered and not name.startswith("."))
        if rest:
            combo.insertSeparator(combo.count())
            for name in rest:
                combo.addItem(name, name)
        return combo

    @staticmethod
    def widget_value(w):
        if isinstance(w, (QLineEdit, ColorField)):
            return w.text()
        if isinstance(w, QComboBox):
            return w.currentData() if w.currentData() is not None else w.currentText()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        return w.value()

    @staticmethod
    def set_widget(w, value):
        if isinstance(w, (QLineEdit, ColorField)):
            w.setText(str(value))
            if isinstance(w,QLineEdit) and not w.hasFocus():w.setCursorPosition(0)
        elif isinstance(w, QComboBox):
            index = w.findData(value)
            if index >= 0:
                w.setCurrentIndex(index)
            else:
                w.setCurrentText(str(value))
        elif isinstance(w, QCheckBox):
            w.setChecked(value)
        else:
            w.setValue(value)

    def execute(self, ops, actor="user"):
        # Render/preflight on a candidate first: invalid fonts/layout do not strand the GUI.
        from .commands import run_operations
        candidate = run_operations(self.project, ops)
        preflight(candidate, dpi=100)
        self.session.execute(ops, actor)
        self.refresh()
        return True

    def refresh(self):
        self._refreshing = True
        try:
            p = self.project
            self.refresh_graph_context()
            dirty = p.fingerprint() != self.saved_hash
            self.setWindowTitle(f"{'● ' if dirty else ''}{p.name} — Scientific Plot Studio {__version__}")
            self.tree.clear()
            root = QTreeWidgetItem([p.name])
            root.setIcon(0, icon("data", self.icon_color))
            root.setToolTip(0, p.name)
            self.tree.addTopLevelItem(root)
            figure_item = QTreeWidgetItem([p.pages[p.context[0]].name+' · '+p.pages[p.context[0]].layers[p.context[1]].name if p.pages else "图形 1 · 单轴区"])
            figure_item.setIcon(0, icon("chart", tokens(self.appearance)["accent"]))
            figure_item.setData(0, Qt.ItemDataRole.UserRole, ("figure", "figure"))
            root.addChild(figure_item)
            selected_item = figure_item if self.active_id == "figure" else None
            axes_item = QTreeWidgetItem(["坐标轴与图例"])
            axes_item.setData(0, Qt.ItemDataRole.UserRole, ("axes", "axes"))
            figure_item.addChild(axes_item)
            if self.active_id == "axes":
                selected_item = axes_item
            for s in p.figure.series:
                item = QTreeWidgetItem([s.label])
                item.setForeground(0, QColor(s.color))
                item.setData(0, Qt.ItemDataRole.UserRole, ("series", s.id))
                item.setCheckState(0, Qt.CheckState.Checked if s.visible else Qt.CheckState.Unchecked)
                item.setToolTip(0, f"{s.label}\nX: {s.x}  Y: {s.y}")
                figure_item.addChild(item)
                if self.active_id == s.id:
                    selected_item = item
            for a in p.figure.annotations:
                item = QTreeWidgetItem(["T  " + a.text[:30]])
                item.setData(0, Qt.ItemDataRole.UserRole, ("annotation", a.id))
                figure_item.addChild(item)
                if self.active_id == a.id:
                    selected_item = item
            data_root = QTreeWidgetItem(["数据集"])
            data_root.setIcon(0, icon("data", self.icon_color))
            root.addChild(data_root)
            for d in p.datasets:
                item = QTreeWidgetItem([d.name])
                item.setToolTip(0, d.name)
                item.setData(0, Qt.ItemDataRole.UserRole, ("dataset", d.id))
                data_root.addChild(item)
                if self.active_id == d.id:
                    selected_item = item
            self.tree.expandAll()
            if selected_item is None and p.figure.series:
                self.active_id = p.figure.series[0].id
                selected_item = figure_item.child(1)
            if selected_item:
                self.tree.setCurrentItem(selected_item)
            if self.dataset_id not in {d.id for d in p.datasets}:
                self.dataset_id = p.datasets[0].id if p.datasets else None
            self.refresh_inspector()
            self.refresh_table()
            self.audit_text.setPlainText(json.dumps(p.audit, ensure_ascii=False, indent=2))
            self.actions["undo"].setEnabled(bool(self.session._undo))
            self.actions["redo"].setEnabled(bool(self.session._redo))
            self.invalidate_review()
            self.invalidate_export()
            if hasattr(self, "ai_panel"):
                self.ai_panel.invalidate()
            self.document_info.setText(f"{p.figure.width_mm:g} × {p.figure.height_mm:g} mm  ·  {p.figure.font} {p.figure.font_size:g} pt")
            self.export_size_info.setText((f"当前图：{p.pages[p.context[0]].name} · 全部图层\n" if p.pages else "") + f"画布 {p.figure.width_mm:g} × {p.figure.height_mm:g} mm\n字体 {p.figure.font}")
            self._update_page_info()
            self.page_frame.set_aspect(p.figure.width_mm, p.figure.height_mm)
            library_error = f" · {len(self.template_library.errors)} 个模板读取失败（悬停查看）" if self.template_library.errors else ""
            self.template_panel.state.setText(f"工程包含 {len(p.datasets)} 组数据；绑定后生成审查预览。" + library_error)
            self.template_panel.apply_button.setEnabled(bool(p.datasets))
            self.filter_project_tree(self.project_filter.text())
            try:
                draw(p, self.canvas.figure)
                self.render_error = None
            except Exception as error:
                # A failed page must never display the previous page's scientific plot.
                self.canvas.figure.clear()
                self.canvas.figure.text(.5, .5, 'Preview unavailable', ha='center')
                self.canvas.draw()
                self.render_error = str(error)
                self.statusBar().showMessage('当前图预览未完成：' + str(error), 20000)
                self.import_summary.setText('当前图预览未完成 · ' + str(error))
                self.import_summary.show()
            self.navigation.update()
        finally:
            self._refreshing = False

    def refresh_inspector(self, follow_selection=False):
        f = self.project.figure
        font_field = self.fig_fields.get("font")
        if isinstance(font_field, QComboBox) and font_field.findData(f.font) < 0:
            font_field.insertItem(0, f.font + "（未安装）", f.font)
        for key, w in self.fig_fields.items():
            value = getattr(f, key)
            if key in ("xlim", "ylim"):
                value = "" if value is None else ", ".join(str(v) for v in value)
            if key in ("x_major_step", "y_major_step") and value is None: value = ""
            if key in ('xlabel_size','ylabel_size','tick_size','legend_size')and value is None:value=0
            self.set_widget(w, value)
        s = next((s for s in f.series if s.id == self.active_id), None)
        self.series_group.setVisible(s is not None)
        if s:
            self.dataset_id = s.dataset
            d = next(d for d in self.project.datasets if d.id == s.dataset)
            self.series_source.setText(f"{d.name} · {s.x} / {s.y}")
            self.series_source.setToolTip(f"数据集：{d.name}\nX：{s.x}\nY：{s.y}\n源行范围（零基半开）：{s.row_range}")
            for key, w in self.series_fields.items():
                self.set_widget(w, getattr(s, key) * 100 if key == "alpha" else getattr(s, key))
        a = next((a for a in f.annotations if a.id == self.active_id), None)
        self.annotation_group.setVisible(a is not None)
        if a:
            for key, w in self.annotation_fields.items():
                self.set_widget(w, getattr(a, key))
        if follow_selection:
            target = 0 if s else 3 if a else 1 if self.active_id == "axes" else 2
            self.property_tabs.setCurrentIndex(target)

    def refresh_table(self):
        self.data_table.blockSignals(True)
        try:
            d = next((d for d in self.project.datasets if d.id == self.dataset_id), None)
            if d is None:
                self.data_table.setRowCount(0)
                self.data_table.setColumnCount(0)
                self.provenance.setText("无数据；导入 CSV/TSV 开始。")
                return
            names = list(d.columns)
            # MVP virtualization boundary: display at most 1000, retain/export ALL rows.
            count = len(d.columns[names[0]])
            limit=200 if self.project.pages else 1000;shown=names[:64]if self.project.pages else names
            self.data_table.setRowCount(min(count,limit));self.data_table.setColumnCount(len(shown))
            self.data_table.setHorizontalHeaderLabels(shown)
            self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive if self.project.pages else QHeaderView.ResizeMode.Stretch)
            if self.project.pages:self.data_table.horizontalHeader().setDefaultSectionSize(170)
            for col, name in enumerate(shown):
                header=self.data_table.horizontalHeaderItem(col)
                if self.project.pages:
                    roles=[]
                    for curve in self.project.figure.series:
                        if curve.dataset!=d.id:continue
                        if curve.x==name and 'X' not in roles:roles.append('X')
                        if curve.y==name and 'Y' not in roles:roles.append('Y')
                        if curve.y_error==name and 'Y误差' not in roles:roles.append('Y误差')
                    header.setText(name+(' ('+'/'.join(roles)+')'if roles else ''))
                    header.setToolTip(name+'\n当前图层引用：'+('/'.join(roles)or '无'))
                    self.data_table.setColumnWidth(col,170)
                for row, value in enumerate(d.columns[name][:limit]):
                    self.data_table.setItem(row, col, QTableWidgetItem('[缺失]'if value is None else value if isinstance(value,str)else format(value, ".10g")))
            self.provenance.setText(("SYNTHETIC · 合成演示数据\n" if d.synthetic else "Imported · 原文件保持不变\n") +
                                    f"{count} rows · {len(names)} columns\n" +
                                    (f"仅显示前 {min(count,limit)} 行 / {len(shown)} 列\n" if count > limit or len(names)>len(shown) else "") +
                                    (f"SHA256 {d.source_sha256[:12]}…" if d.source_sha256 else ""))
        finally:
            self.data_table.blockSignals(False)

    def tree_selected(self):
        if self._refreshing:
            return
        item = self.tree.currentItem()
        payload = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if payload:
            kind, ident = payload
            self.active_id = ident
            if kind == "dataset":
                self.dataset_id = ident
            self.refresh_inspector(follow_selection=True)
            self.refresh_table()

    def tree_visibility_changed(self, item, column):
        if self._refreshing:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload and payload[0] == "series":
            ident = payload[1]
            visible = item.checkState(0) == Qt.CheckState.Checked
            current = next((s for s in self.project.figure.series if s.id == ident), None)
            if current and (current.visible != visible or ident in self._pending_visibility):
                # Qt is still using this item while emitting itemChanged. A
                # synchronous refresh would delete it on its own C++ stack.
                self._pending_visibility[ident] = visible
                self.visibility_timer.start(0)

    def flush_tree_visibility(self):
        pending, self._pending_visibility = self._pending_visibility, {}
        operations = []
        for visible in (False, True):
            ids = [s.id for s in self.project.figure.series if pending.get(s.id) is visible and s.visible != visible]
            if ids:
                operations.append({"op": "set_series", "ids": ids, "changes": {"visible": visible}})
        if operations and not self.guard(lambda: self.execute(operations)):
            self.refresh()

    def pick_object(self, event):
        ident = event.artist.get_gid()
        if ident:
            if self.project.pages:
                pi,_=self.project.context
                for li,layer in enumerate(self.project.pages[pi].layers):
                    if any(o.id==ident for o in layer.figure.series+layer.figure.annotations):
                        self.project.select_context(pi,li);self.refresh();break
            self.active_id = ident
            self.refresh_inspector(follow_selection=True)
            self.refresh_table()

    def apply_figure(self):
        def apply():
            changes = {k: self.widget_value(w) for k, w in self.fig_fields.items()}
            for key in ("xlim", "ylim"):
                raw = changes[key].strip()
                changes[key] = None if raw.lower() in ("", "auto") else [float(v.strip()) for v in raw.split(",")]
            for key in ("x_major_step", "y_major_step"):
                raw = changes[key].strip()
                changes[key] = None if raw.lower() in ("", "auto") else float(raw)
            for key in ('xlabel_size','ylabel_size','tick_size','legend_size'):
                if changes.get(key)==0:changes[key]=None
            self.execute([{"op": "set_figure", "changes": changes}])
        self.guard(apply)

    def apply_series(self):
        def apply():
            changes = {k: self.widget_value(w) for k, w in self.series_fields.items()}
            changes["alpha"] /= 100
            ids = [self.active_id]
            if self.batch_all.isChecked():
                ids = [s.id for s in self.project.figure.series]
                # Labels, error mapping, plot types and visibility remain individually meaningful.
                changes = {k: v for k, v in changes.items() if k in {"color", "width", "marker", "marker_size", "line_style", "alpha"}}
            self.execute([{"op": "set_series", "ids": ids, "changes": changes}])
        self.guard(apply)

    def apply_annotation(self):
        self.guard(lambda: self.execute([{"op": "set_annotation", "id": self.active_id,
                                          "changes": {k: self.widget_value(w) for k, w in self.annotation_fields.items()}}]))

    def cell_changed(self, item):
        if self._refreshing:
            return
        def apply():
            d=next(d for d in self.project.datasets if d.id == self.dataset_id);names=list(d.columns)
            value=None if d.allow_missing and item.text().strip()in('','[缺失]')else item.text()if names[item.column()]in d.text_columns else float(item.text())
            self.execute([{"op": "set_cell", "dataset": self.dataset_id, "column": names[item.column()],
                           "row": item.row(), "value": value}])
        if self.guard(apply) is None:
            self.refresh_table()

    def import_data(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "导入数据或Origin工程", "", "数据与Origin (*.csv *.tsv *.txt *.opj *.opju);;所有文件 (*)")
        if not path:
            return
        if Path(path).suffix.lower()in('.opj','.opju'):
            self.open_origin(path);return
        def apply():
            d = import_table(path)
            dialog = MappingDialog(d, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                s = dialog.series(d, len(self.project.figure.series))
                self.execute([{"op": "add_dataset", "dataset": asdict(d)}, {"op": "add_series", "series": asdict(s)}])
                self.active_id = s.id
                self.dataset_id = d.id
                self.refresh()
        self.guard(apply)

    def add_plot(self):
        d = next((d for d in self.project.datasets if d.id == self.dataset_id), None)
        if d is None:
            self.import_data()
            return
        dialog = MappingDialog(d, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            s = dialog.series(d, len(self.project.figure.series))
            self.active_id = s.id
            self.guard(lambda: self.execute([{"op": "add_series", "series": asdict(s)}]))

    def add_annotation(self):
        a = Annotation(uid("text"), "(a)")
        self.active_id = a.id
        self.guard(lambda: self.execute([{"op": "add_annotation", "annotation": asdict(a)}]))
        self.refresh_inspector(follow_selection=True)

    def remove_object(self):
        if any(s.id == self.active_id for s in self.project.figure.series):
            self.guard(lambda: self.execute([{"op": "remove_series", "id": self.active_id}]))
        elif any(a.id == self.active_id for a in self.project.figure.annotations):
            self.guard(lambda: self.execute([{"op": "remove_annotation", "id": self.active_id}]))

    def undo(self):
        if self.session.undo():
            self.refresh()

    def redo(self):
        if self.session.redo():
            self.refresh()

    def may_discard(self):
        if self.project.fingerprint() == self.saved_hash:
            return True
        answer = QMessageBox.question(self, "尚未保存修改", "保存当前修改后再继续？", QMessageBox.StandardButton.Save |
                                       QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                       QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def replace_project(self, project, path=None, *, check_layout=True):
        if check_layout:preflight(project, 100)
        else:project.validate()
        self.visibility_timer.stop()
        self._pending_visibility.clear()
        self.session = Session(project)
        self.project_path = Path(path) if path else None
        self.figure_path=None;self.figure_sha=None
        self.saved_hash = self.project.fingerprint()
        self.active_id = None
        self.dataset_id = None
        self.refresh()

    def new_project(self):
        if self.may_discard():
            self.guard(lambda: self.replace_project(Project()))

    def load_demo(self):
        if self.may_discard():
            self.guard(lambda: self.replace_project(demo()))

    def open_project(self, path=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "打开工程或分析 Origin", "", "SPS / Origin / Office / 图形 (*.sps.json *.spsfig *.opj *.opju *.pptx *.docx *.png *.svg);;All files (*)")
        if not path:
            return
        if str(path).startswith('spsfigure:'):
            from .figure_links import resolve
            return self.guard(lambda:self.open_project(resolve(str(path),self.figure_links_root)))
        suffix=Path(path).suffix.lower()
        if suffix in('.spsfig','.png','.svg'):
            return self.guard(lambda:self.open_figure_object(path))
        if suffix in('.docx','.pptx'):
            from .office import package
            from .office_figures import MANIFEST
            def kind_of_office():
                with package(path)as archive:return MANIFEST in archive.namelist()
            has_figure=self.guard(kind_of_office)
            if has_figure is None:return
            if has_figure or suffix=='.docx':return self.guard(lambda:self.recover_office_figure(path))
        if Path(path).suffix.lower()=='.pptx':
            from .office import package
            from .pptx_io import PART
            def run():
                with package(path) as archive:is_sps=PART in archive.namelist()
                if is_sps:self.recover_pptx(path)
                else:
                    self.workspaces.setCurrentIndex(self.office_index);self.office_panel.scan(path)
            self.guard(run)
            return
        if Path(path).suffix.lower() in (".opj", ".opju"):
            self.open_origin(path)
            return
        if self.may_discard():
            self.guard(lambda: self.replace_project(load(path), path))

    def save_project(self, save_as=False, path=None):
        if self.figure_path and not save_as and path is None:
            return self.save_figure_object()
        if path is None:
            path = None if save_as else self.project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "保存可编辑 SPS 工程", "untitled.sps.json", "SPS (*.sps.json)")
        if not path:
            return False
        if not str(path).endswith(".sps.json"):
            path = str(path) + ".sps.json"
        try:
            save(self.project, path)
            self.project_path = Path(path)
            self.figure_path=None;self.figure_sha=None
            self.saved_hash = self.project.fingerprint()
            self.refresh()
            self.statusBar().showMessage("已保存 · " + str(path), 10000)
            return True
        except Exception as e:
            QMessageBox.warning(self, "保存未完成", str(e))
            return False

    def closeEvent(self, event):
        if any(getattr(self, name, None) is not None and getattr(self, name).busy for name in ("origin_panel", "ai_panel", "office_panel")):
            self.statusBar().showMessage("后台任务正在结束；结果返回后可关闭窗口。", 8000)
            event.ignore()
            return
        if self.may_discard():
            event.accept()
        else:
            event.ignore()

    def choose_export_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.export_dir.text())
        if path:
            self.export_dir.setText(path)

    def set_preview_background(self):
        mode = ("checker", "white", "black")[self.preview_background.currentIndex()]
        self.export_preview.set_background(mode)
        self.svg_preview.set_background(mode)

    def go_to_canvas(self):
        self.workspaces.setCurrentIndex(self.editor_index)
        self.property_tabs.setCurrentIndex(2)

    def export_basis(self):
        return (self.project.fingerprint(), self.project.context[0], self.export_dir.text(), self.export_stem.text(),
                self.export_dpi.value(), self.transparent.isChecked(),
                tuple(fmt for fmt, check in self.format_checks.items() if check.isChecked()))

    def set_export_checks(self, report=None):
        files = {f["format"]: f for f in report["files"]} if report else {}
        descriptions = {"png": "像素尺寸 / Alpha", "svg": "画布尺寸 / 文字轮廓", "pdf": "页尺寸 / 字体嵌入", "tiff": "像素尺寸 / Alpha"}
        for row, fmt in enumerate(("png", "svg", "pdf", "tiff")):
            selected = self.format_checks[fmt].isChecked()
            passed = fmt in files
            values = (fmt.upper(), "通过" if passed else "待导出" if selected else "未选择", descriptions[fmt])
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 1:
                    item.setForeground(QColor("#218268" if passed else "#7c8792"))
                self.export_checks.setItem(row, col, item)
        for col, value in enumerate(("跨平台 / 外部软件", "未验证", "Windows / Office / PDF 阅读器待验收")):
            self.export_checks.setItem(4, col, QTableWidgetItem(value))

    def invalidate_export(self):
        if getattr(self, "_export_basis", None) == self.export_basis():
            return
        self.last_export = None
        self._export_basis = None
        self.export_preview.set_image(QPixmap())
        self.svg_preview.set_image(QPixmap())
        self.set_export_checks()
        self.export_report.setPlainText("当前设置尚未导出校验；请预检或重新导出。")

    def run_preflight(self):
        def run():
            fig, report = preflight(self.project, self.export_dpi.value())
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100, transparent=self.transparent.isChecked(), bbox_inches=None)
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue())
            self.export_preview.set_image(pixmap)
            self.export_report.setPlainText(
                f"预检通过 · {report['width_mm']:g} × {report['height_mm']:g} mm · {report['dpi']} DPI\n"
                f"字体/字形：{report['font']['family']} ✓ · 可见文字位于画布内 ✓\n"
                "左侧为预检渲染；实际文件检查在导出后进行。")
        self.guard(run)

    def do_export(self):
        def run():
            report = export_bundle(self.project, self.export_dir.text(), self.export_stem.text(),
                                   [fmt for fmt, w in self.format_checks.items() if w.isChecked()],
                                   self.export_dpi.value(), self.transparent.isChecked())
            directory = Path(self.export_dir.text())
            names = {f["format"]: f["name"] for f in report["files"]}
            if "png" in names:
                self.export_preview.set_image(QPixmap(str(directory / names["png"])))
            else:
                self.run_preflight()
            svg_note = "SVG 未选择"
            preview_error = None
            if "svg" in names:
                try:
                    self.svg_preview.set_image(svg_pixmap(directory / names["svg"]))
                    svg_note = "SVG 已由本机 Qt 阅读器渲染"
                except Exception as e:
                    self.svg_preview.set_image(QPixmap())
                    svg_note = f"文件检查通过，但本机 SVG 预览失败：{e}"
                    preview_error = str(e)
            self.last_export = report
            self._export_basis = self.export_basis()
            self.set_export_checks(report)
            if preview_error:
                failed = QTableWidgetItem("预览失败")
                failed.setForeground(QColor("#bf7628"))
                self.export_checks.setItem(1, 1, failed)
                self.export_checks.setItem(1, 2, QTableWidgetItem("结构检查通过；本机阅读器未通过"))
            if "svg" in names:
                from PySide6.QtCore import qVersion
                write_json(directory / f"{self.export_stem.text()}.preview.json", {
                    "schema": "sps.preview/1", "project_hash": self.project.fingerprint(),
                    "file": names["svg"], "renderer": "Qt SVG", "qt_version": qVersion(),
                    "platform": capabilities()["platform"], "passed": preview_error is None,
                    "error": preview_error, "scope": "本机阅读器可加载且无警告；不代表像素一致性或跨平台验收"})
            self.export_report.setPlainText(f"{len(report['files'])} 种格式验证通过 · {svg_note}\n"
                                            f"完整报告：{self.export_stem.text()}.export.json")
            self.statusBar().showMessage(f"已导出并校验 {len(report['files'])} 个文件 · {directory}", 15000)
        self.guard(run)

    def invalidate_review(self):
        self.pending_review = None
        self.review_items = []
        if hasattr(self, "planner_summary"):
            self.planner_summary.hide()
        if hasattr(self, "apply_review_button"):
            self.apply_review_button.setEnabled(False)
            self.review_table.blockSignals(True)
            self.review_table.setRowCount(0)
            self.review_table.blockSignals(False)
            self.review_summary.setText("尚无有效审查；请载入风格或预览操作计划。")
            self.agent_diff.setPlainText("修改输入或工程后需重新审查。")
            self.before_preview.clear()
            self.before_preview.setText("当前图形")
            self.after_preview.clear()
            self.after_preview.setText("所选修改预览")

    def preview_agent(self):
        def run():
            self.invalidate_review()
            operations = json.loads(self.agent_input.toPlainText())
            self.review_items = review_rows(self.project, operations)
            self._review_base = self.project.fingerprint()
            self.review_table.blockSignals(True)
            try:
                self.review_table.setRowCount(len(self.review_items))
                for row, change in enumerate(self.review_items):
                    check = QTableWidgetItem()
                    check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                    check.setCheckState(Qt.CheckState.Checked)
                    self.review_table.setItem(row, 0, check)
                    for col, key in enumerate(("label", "before", "after", "impact"), 1):
                        value = display_value(change[key])
                        item = QTableWidgetItem(value)
                        item.setToolTip(value)
                        self.review_table.setItem(row, col, item)
            finally:
                self.review_table.blockSignals(False)
            self.update_selected_review()
        self.guard(run)

    def review_selection_changed(self, item):
        if item.column() == 0:
            self.update_selected_review()

    def update_selected_review(self):
        from .commands import run_operations
        # Rebuild the reviewed plan from the checkboxes. The old complete plan is
        # never applied after the user deselects a property.
        self.pending_review = None
        self.apply_review_button.setEnabled(False)
        selected = [self.review_table.item(i, 0).checkState() == Qt.CheckState.Checked for i in range(len(self.review_items))]
        operations = selected_operations(self.review_items, selected)
        try:
            if self.project.fingerprint() != self._review_base:
                raise ValueError("工程已变化，请重新审查")
            candidate = run_operations(self.project, operations) if operations else self.project
            preflight(candidate, 100)
            for project, w in [(self.project, self.before_preview), (candidate, self.after_preview)]:
                fig, *_ = preflight(project, 100)
                buffer = io.BytesIO()
                fig.savefig(buffer, format="png", dpi=180)
                pix = QPixmap()
                pix.loadFromData(buffer.getvalue())
                w.setPixmap(pix)
            if operations:
                self.pending_review = self.session.preview(operations)
                self.agent_diff.setPlainText(json.dumps(self.pending_review, ensure_ascii=False, indent=2))
                self.apply_review_button.setEnabled(bool(self.pending_review["changes"]))
            else:
                self.agent_diff.setPlainText("未勾选修改；工程保持当前状态。")
            self.review_summary.setText(f"已勾选 {sum(selected)} / {len(selected)} 项 · 尚未应用 · 应用后可撤销")
        except Exception as e:
            self.after_preview.clear()
            self.after_preview.setText("所选组合无效；请调整勾选项")
            self.review_summary.setText(f"无法应用所选项：{e}")
            self.agent_diff.setPlainText(str(e))

    def apply_agent(self):
        def run():
            if self.pending_review is None:
                raise ValueError("请先预览并审查当前操作")
            is_template = any(op["op"] == "apply_template" for op in self.pending_review["operations"])
            self.session.apply_review(self.pending_review)
            self.refresh()
            if is_template:
                self.workspaces.setCurrentIndex(self.editor_index)
                self.property_tabs.setCurrentIndex(0)
                self.statusBar().showMessage("模板已套用 · 全部原始数据保留 · 可撤销", 12000)
        self.guard(run)

    def extract_style(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存当前风格", "personal.sps-style.json", "SPS 风格 (*.json)")
        if path:
            self.guard(lambda: write_json(path, style_from_project(self.project)))

    def propose_style(self, style):
        self.agent_input.setPlainText(json.dumps([{"op": "apply_style", "style": style}], ensure_ascii=False, indent=2))
        self.preview_agent()

    def load_style(self):
        path, _ = QFileDialog.getOpenFileName(self, "载入风格", "", "SPS 风格 (*.json)")
        if path:
            self.guard(lambda: self.propose_style(read_json(path)))

    def style_from_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "从 SPS 工程提取风格", "", "SPS (*.sps.json)")
        if path:
            self.guard(lambda: self.propose_style(style_from_project(load(path))))

    def open_figure_object(self,path):
        from . import figure_object as figure,figure_links
        path=Path(path)
        if path.stat().st_size>110_000_000:raise ValueError('图形对象或携带数据的图像超过读取限制')
        if path.suffix.lower()=='.spsfig':info=figure.load(path)
        else:
            info=figure.from_png(path.read_bytes())if path.suffix.lower()=='.png'else figure.from_svg(path.read_bytes())
            path=figure_links.restore(info['package'],self.figure_links_root)
        if not self.may_discard():return
        figure_links.register(path,self.figure_links_root)
        self.replace_project(info['project'],check_layout=False)
        self.figure_path=path.resolve();self.figure_sha=info['sha256']
        self.statusBar().showMessage('已打开可编辑图形对象 · 保存将更新对象；Office 图像通过“生成更新副本”同步',16000)

    def export_figure_object(self,path=None):
        if not path:
            path,_=QFileDialog.getSaveFileName(self,'导出可编辑图形对象：含完整工程和原始数据','figure.spsfig','SPS 图形对象 (*.spsfig)')
        if not path:return
        def run():
            from . import figure_object as figure,figure_links
            target=Path(path);target=target if target.suffix.lower()=='.spsfig'else target.with_suffix('.spsfig')
            info=figure.save(self.project,target);figure_links.register(target,self.figure_links_root)
            self.statusBar().showMessage('已导出可编辑图形对象 · '+str(target),12000);return info
        return self.guard(run)

    def save_figure_object(self):
        def run():
            from . import figure_object as figure,figure_links
            figure_links.register(self.figure_path,self.figure_links_root)
            info=figure.save(self.project,self.figure_path,expected_sha=self.figure_sha)
            self.figure_sha=info['sha256'];self.saved_hash=self.project.fingerprint()
            figure_links.register(self.figure_path,self.figure_links_root);self.refresh()
            self.statusBar().showMessage('图形对象已保存 · Office 文档请生成更新副本；原文档未改写',15000)
            return True
        return bool(self.guard(run))

    def copy_office_figure(self):
        def run():
            from .figure_links import mime_data
            mime,item=mime_data(self.project,self.figure_links_root);QApplication.clipboard().setMimeData(mime)
            self.statusBar().showMessage('已复制图像 · 本机保留完整工程；普通粘贴可能丢弃编辑入口，请使用“导出带编辑入口的 Word / PPT”',18000)
            return item
        return self.guard(run)

    def export_linked_assets(self,directory=None):
        if not directory:
            directory,_=QFileDialog.getSaveFileName(self,'新建链接资源文件夹','SPS-linked-figure','文件夹 (*)')
        if not directory:return
        def run():
            from .figure_assets import export
            result=export(self.project,directory,self.figure_links_root)
            self.statusBar().showMessage('已导出链接资源包 · 在Illustrator以链接方式置入figure.svg；可选脚本返回SPS，宿主尚未实测',18000)
            return result
        return self.guard(run)

    def refresh_linked_assets(self):
        def run():
            from .figure_assets import refresh
            if not self.figure_path:raise ValueError('请先打开链接资源包中的figure.spsfig，编辑并保存')
            if self.project.fingerprint()!=self.saved_hash:raise ValueError('请先保存当前图形对象，再更新链接预览')
            result=refresh(self.figure_path.parent)
            self.statusBar().showMessage('链接SVG / PNG已更新 · 请在宿主中更新链接并检查',15000)
            return result
        return self.guard(run)

    def export_office_figure(self,path=None):
        if not path:
            path,kind=QFileDialog.getSaveFileName(self,'导出带编辑入口的图像：含完整SPS工程','figure.pptx','PowerPoint (*.pptx);;Word (*.docx)')
            if path and not Path(path).suffix:path+=('.docx'if 'docx'in kind else'.pptx')
        if not path:return
        def run():
            from .office_figures import export
            result=export(self.project,path,self.figure_links_root)
            self.statusBar().showMessage('已生成带 SPS 编辑链接的文档 · 链接不等同 OLE 双击；'+str(path),16000);return result
        return self.guard(run)

    def recover_office_figure(self,path):
        from .office_figures import recover
        from .figure_links import restore
        objects=recover(path)
        index=0
        if len(objects)>1:
            names=[str(i+1)+'. '+o['info']['project'].name for i,o in enumerate(objects)]
            selected,ok=QInputDialog.getItem(self,'选择恢复的 SPS 图形','工程（含完整原始数据）',names,0,False)
            if not ok:return
            index=names.index(selected)
        target=restore(objects[index]['package'],self.figure_links_root)
        self.open_figure_object(target)

    def refresh_office_figure(self,source=None,target=None):
        if not source:source,_=QFileDialog.getOpenFileName(self,'选择已保存的Word/PPT：更新将另存副本','','Office (*.docx *.pptx)')
        if not source:return
        if not target:target,_=QFileDialog.getSaveFileName(self,'另存更新后的文档，保留原件',str(Path(source).with_stem(Path(source).stem+'-SPS更新')),'Office (*.docx *.pptx)')
        if not target:return
        def run():
            from .office_figures import refresh
            result=refresh(source,target,self.figure_links_root)
            warning=' · 图形宽高比已改变，宿主尺寸保留，请检查拉伸'if any(e['aspect_changed']for e in result['updated'])else''
            self.statusBar().showMessage('更新副本已生成，宿主位置/裁切保留；请打开新文档检查'+warning+' · '+str(target),20000);return result
        return self.guard(run)

    def edit_axis_sides(self):
        dialog=AxesDialog(self.project.figure,self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.guard(lambda:self.execute([{'op':'set_figure','changes':{'axis_sides':dialog.settings()}}]))

    def publication_dialog(self):
        dialog=PublicationDialog(self.session,self.publication_preferences,self)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.plan:
            def apply():
                self.session.apply_review(dialog.plan,actor='publication_reviewed')
                self.publication_preferences=dialog.preferences()
                write_json(self.publication_settings,self.publication_preferences)
                self.refresh()
                self.statusBar().showMessage('已统一轴与字体 · 曲线样式保持 · 可撤销 · 请逐图检查',15000)
            self.guard(apply)

    def batch_publication(self):
        if self.office_panel.busy:
            self.statusBar().showMessage('请等待当前后台任务完成。',8000);return
        dialog=PublicationDialog(self.session,self.publication_preferences,self,batch=True)
        if dialog.exec()!=QDialog.DialogCode.Accepted or not dialog.plan:return
        files,_=QFileDialog.getOpenFileNames(self,'选择多个Origin工程','','Origin (*.opj *.opju)')
        if not files:return
        directory=QFileDialog.getExistingDirectory(self,'选择输出父文件夹：将创建新文件夹')
        if not directory:return
        target=Path(directory)/('SPS-规范化-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
        options=dialog.options();probe=self.office_panel.probe.text();decoder=self.office_panel.decoder.text()
        from .publication import batch_import
        def done(report):
            saved=sum(f['status']=='saved'for f in report['files'])
            self.office_panel.status.setText(f'批量完成：{saved}/{len(files)} 工程保存；失败与逐页检查见 '+str(target/'batch-report.json'))
            self.publication_preferences=dialog.preferences();write_json(self.publication_settings,self.publication_preferences)
            self.statusBar().showMessage('规范化结果已另存：'+str(target),20000)
        self.workspaces.setCurrentIndex(self.office_index)
        self.office_panel.work(lambda:batch_import(files,target,options,probe or None,decoder or None),done)

    def show_bridge(self):
        data = capabilities()
        QMessageBox.information(self, "Origin 兼容能力", data["message"] + "\n\n" + data["fallback"] +
                                "\n\n独立 OTP/OTPU/OTH 解析尚未实现；旧 OPJ 的逐层部分风格/模板入口在 Origin 分析页。")


class SPSApplication(QApplication):
    fileRequested=Signal(str)
    def __init__(self,argv):
        super().__init__(argv);self.pending_files=[];self.ready=False
    def event(self,event):
        if event.type()==QEvent.Type.FileOpen:
            target=event.file()or event.url().toString()
            if self.ready:self.fileRequested.emit(target)
            else:self.pending_files.append(target)
            return True
        return super().event(event)


def run(project_path=None):
    app = QApplication.instance() or SPSApplication([])
    app.setApplicationName("Scientific Plot Studio")
    app.setOrganizationName("SPS")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    if isinstance(app,SPSApplication):
        app.fileRequested.connect(window.open_project);app.ready=True
        for target in app.pending_files:QTimer.singleShot(0,lambda t=target:window.open_project(t))
        app.pending_files.clear()
    if project_path:
        QTimer.singleShot(0, lambda: window.open_project(project_path))
    return app.exec()
