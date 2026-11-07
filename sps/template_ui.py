"""Native template library and explicit binding dialogs (presentation only)."""
import io

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                              QCheckBox, QComboBox, QGroupBox, QFormLayout,
                              QDialogButtonBox, QListWidget, QListWidgetItem, QPushButton, QScrollArea)

from . import templates
from .commands import run_operations
from .render import preflight
from .ui_helpers import HelpDisclosure,style_scroll_surface


def note(text, heading=False):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setProperty("muted", not heading)
    if heading:
        label.setProperty("heading", True)
    return label


class CaptureTemplateDialog(QDialog):
    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存为原生模板")
        self.resize(490, 310)
        layout = QVBoxLayout(self)
        layout.addWidget(note("将当前图形保存成可重复套用的模板", True))
        form = QFormLayout()
        self.name = QLineEdit(project.name + " 模板")
        self.description = QLineEdit()
        self.description.setPlaceholderText("适用的数据和使用说明（可选）")
        self.keep_ranges = QCheckBox("保留当前坐标范围（否则随新数据自动调整）")
        self.keep_annotations = QCheckBox("保留文字注释（套用时需确认是否适用）")
        self.keep_annotations.setChecked(True)
        form.addRow("模板名称", self.name)
        form.addRow("说明", self.description)
        form.addRow(self.keep_ranges)
        form.addRow(self.keep_annotations)
        layout.addLayout(form)
        layout.addWidget(note("不保存数据数值。轴标签、标题和图例在绑定新数据时重新填写；不推断或转换单位。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存模板")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def template(self, project):
        template = templates.extract(project, self.name.text().strip(), self.keep_ranges.isChecked())
        template.description = self.description.text()
        if not self.keep_annotations.isChecked():
            template.annotations = []
        return template.validate()


class TemplateBindingDialog(QDialog):
    def __init__(self, project, template, parent=None):
        super().__init__(parent)
        self.project, self.template = project, template
        self.setObjectName("template_binding_dialog")
        self.setWindowTitle("绑定新数据 · " + template.name)
        self.resize(720, min(850, 570 + len(template.slots) * 70))
        layout = QVBoxLayout(self)
        layout.addWidget(note("明确选择每条曲线的数据，再审查图形变化", True))
        layout.addWidget(note("此操作会替换当前图形布局和曲线，保留所有数据集；应用后可撤销。"))
        self.partial_ack = None
        if template.source.get("kind") == "origin_partial":
            layout.addWidget(note(template.description))
            self.partial_ack = QCheckBox("我已查看部分转换范围，接受未映射对象不进入当前单层模板")
            layout.addWidget(self.partial_ack)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        fields = QWidget()
        fields_layout = QVBoxLayout(fields)
        fields_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows = []
        for index, slot in enumerate(template.slots):
            group = QGroupBox(f"{index + 1:02d}  {slot.name}")
            form = QFormLayout(group)
            dataset = QComboBox()
            for d in project.datasets:
                dataset.addItem(d.name, d.id)
            x, y, error = QComboBox(), QComboBox(), QComboBox()
            legend = QLineEdit()
            legend.setPlaceholderText("默认使用 Y 列名")
            row = {"slot": slot.id, "dataset": dataset, "x": x, "y": y, "error": error, "legend": legend}
            self.rows.append(row)
            form.addRow("数据集", dataset)
            coordinates = QHBoxLayout()
            coordinates.addWidget(QLabel("X"))
            coordinates.addWidget(x, 1)
            coordinates.addWidget(QLabel("Y"))
            coordinates.addWidget(y, 1)
            form.addRow("数据列", coordinates)
            if slot.properties.get("kind") == "errorbar":
                form.addRow("Y 误差列（必选）", error)
            else:
                error.hide()
            form.addRow("图例", legend)
            dataset.currentIndexChanged.connect(lambda ignored=0, r=row, i=index: self.fill_columns(r, i))
            self.fill_columns(row, index)
            fields_layout.addWidget(group)
        scroll.setWidget(fields)
        style_scroll_surface(scroll)
        layout.addWidget(scroll, 1)
        labels = QGroupBox("确认标题与单位")
        form = QFormLayout(labels)
        self.labels = {"title": QLineEdit(""), "x_label": QLineEdit(self.rows[0]["x"].currentText() if self.rows else "X"),
                       "y_label": QLineEdit(self.rows[0]["y"].currentText() if self.rows else "Y")}
        for key, title in [("title", "标题"), ("x_label", "X 轴标签 / 单位"), ("y_label", "Y 轴标签 / 单位")]:
            form.addRow(title, self.labels[key])
        form.addRow(HelpDisclosure("不会继承旧数据的单位或样本名称，也不执行单位换算；请填写新数据对应的轴标签与图例。", "新数据标签"))
        layout.addWidget(labels)
        if template.annotations:
            layout.addWidget(note(f"模板保留 {len(template.annotations)} 处注释，下一步请核对静态文字是否适用于新数据。"))
        self.error_message = note("")
        self.error_message.setStyleSheet("color:#b75b36;")
        layout.addWidget(self.error_message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("生成审查预览")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def fill_columns(self, row, index):
        ident = row["dataset"].currentData()
        d = next((d for d in self.project.datasets if d.id == ident), None)
        names = list(d.columns) if d else []
        for key in ("x", "y", "error"):
            row[key].clear()
            row[key].addItems((["请选择误差列"] if key == "error" else []) + names)
        row["y"].setCurrentIndex(min(1 + index, len(names) - 1))

    def operation(self):
        if self.partial_ack is not None and not self.partial_ack.isChecked():
            raise ValueError("请先确认 Origin 部分模板的转换范围")
        bindings = []
        for row in self.rows:
            binding = {"slot": row["slot"], "dataset": row["dataset"].currentData(),
                       "x": row["x"].currentText(), "y": row["y"].currentText(),
                       "y_error": row["error"].currentText() if row["error"].currentIndex() > 0 else ""}
            if row["legend"].text().strip():
                binding["legend"] = row["legend"].text().strip()
            bindings.append(binding)
        return {"op": "apply_template", "template": self.template.to_dict(), "bindings": bindings,
                "labels": {k: w.text() for k, w in self.labels.items()}}

    def accept(self):
        try:
            preflight(run_operations(self.project, [self.operation()]), 100)
        except Exception as e:
            self.error_message.setText(str(e))
            return
        super().accept()


class TemplateLibraryPanel(QWidget):
    captureRequested = Signal()
    importRequested = Signal()
    exportRequested = Signal()
    applyRequested = Signal()

    def __init__(self, preview_factory):
        super().__init__()
        self.catalog = []
        self.last_preview_project = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        title = note("模板库", True)
        title.setObjectName("workspace_title")
        layout.addWidget(title)
        layout.addWidget(note("选择模板 → 绑定数据 → 审查应用"))
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, signal in [("从当前图形保存", self.captureRequested), ("导入 SPS 模板", self.importRequested),
                             ("导出选中模板", self.exportRequested)]:
            btn = QPushButton(text)
            btn.clicked.connect(signal.emit)
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        content = QHBoxLayout()
        self.list = QListWidget()
        self.list.setObjectName("template_list")
        self.list.setMinimumWidth(205)
        self.list.setMaximumWidth(260)
        self.list.setSpacing(6)
        self.list.currentRowChanged.connect(self.selection_changed)
        content.addWidget(self.list, 1)
        right = QVBoxLayout()
        right.addWidget(note("模板预览 · 合成数据，不代表实验结果"))
        self.preview = preview_factory()
        self.preview.set_background("white")
        self.preview.empty_text = "选择左侧模板"
        right.addWidget(self.preview, 1)
        self.details = note("")
        right.addWidget(self.details)
        content.addLayout(right, 2)
        layout.addLayout(content, 1)
        self.state = note("")
        layout.addWidget(self.state)
        self.apply_button = QPushButton("绑定新数据并预览")
        self.apply_button.setObjectName("bind_template")
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self.applyRequested.emit)
        layout.addWidget(self.apply_button)

    def selected_template(self):
        index = self.list.currentRow()
        return self.catalog[index][0] if 0 <= index < len(self.catalog) else None

    def set_catalog(self, items, selected_hash=None):
        self.list.blockSignals(True)
        self.list.clear()
        self.catalog = items
        selected = 0
        for index, (template, source) in enumerate(items):
            f = template.figure
            provenance = "Origin 层部分转换" if template.source.get("kind") == "origin_partial" else "SPS 原生"
            suffix = "" if provenance == "SPS 原生" else " · " + provenance
            item = QListWidgetItem(
                f"{template.name}\n{len(template.slots)} 条曲线 · {f.get('font', 'Arial')} {f.get('font_size', 10):g} pt\n"
                f"{f.get('width_mm', 160):g} × {f.get('height_mm', 110):g} mm · {source}{suffix}")
            item.setSizeHint(QSize(205, 88))
            item.setToolTip(template.description or template.name)
            self.list.addItem(item)
            if template.fingerprint() == selected_hash:
                selected = index
        self.list.setCurrentRow(selected if items else -1)
        self.list.blockSignals(False)
        self.selection_changed()

    def selection_changed(self):
        template = self.selected_template()
        self.last_preview_project = None
        if template is None:
            return
        try:
            p = templates.preview_project(template)
            figure, _ = preflight(p, 100)
            output = io.BytesIO()
            figure.savefig(output, format="png", dpi=300)
            image = QPixmap()
            image.loadFromData(output.getvalue())
            self.preview.set_image(image)
            self.last_preview_project = p
            provenance = "Origin 所选层部分转换；未映射项使用 SPS 默认值，绑定前需确认范围。\n" if template.source.get("kind") == "origin_partial" else ""
            self.details.setToolTip(template.description)
            self.details.setText(provenance + f"{template.figure.get('font', 'Arial')} · {len(template.annotations)} 处注释\n"
                                 "标题、轴标签和图例将在绑定时更新；不会复制旧数据。")
        except Exception as e:
            self.preview.set_image(QPixmap())
            self.details.setText("模板预览失败：" + str(e))
