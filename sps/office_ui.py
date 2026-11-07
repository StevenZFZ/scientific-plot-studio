"""Clipboard / editable Office transfer and explicit Origin data recovery."""
from .local_paths import data_dir
from pathlib import Path
import os
import math
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QLineEdit,
                              QComboBox, QPlainTextEdit, QFileDialog, QTableWidget,QSplitter,
                              QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox, QSpinBox, QTabWidget, QWidget, QPushButton)
from .workflow_ui import WorkPanel, action
from .template_ui import note
from . import office, origin_data
from .model import write_json
from .ui_helpers import HelpDisclosure


class OfficePanel(WorkPanel):
    importRequested=Signal(str)
    projectReady = Signal(object)
    copyRequested = Signal()
    pasteRequested = Signal()
    exportRequested = Signal()
    recoverRequested = Signal()
    def __init__(self, parent=None):
        super().__init__(parent); self.report=None; self.recovery=None; self.pairs=[]; self.recovered_dir=None; self.input_generation=0
        layout=QVBoxLayout(self); layout.setContentsMargins(18,16,18,14)
        layout.addWidget(note('Origin 数据与 Office 互通', True))
        layout.addWidget(HelpDisclosure('部分恢复原始数据与可编辑工程，不执行Origin脚本、公式或嵌入对象；未支持的列会明确列出。','读取范围'))
        self.sections=QTabWidget();layout.addWidget(self.sections,1)
        data_page=QWidget();data_layout=QVBoxLayout(data_page)
        transfer_page=QWidget();transfer_layout=QVBoxLayout(transfer_page)
        self.sections.addTab(data_page,'Origin 数据读取与重绘')
        self.sections.addTab(transfer_page,'复制与 PPT 恢复')
        transfer_buttons=QHBoxLayout()
        for title,signal in [('复制工程与图像',self.copyRequested),('粘贴 SPS 工程',self.pasteRequested),
                             ('导出可编辑 PPTX',self.exportRequested),('恢复 SPS 工程',self.recoverRequested)]:
            transfer_buttons.addWidget(action(title,lambda checked=False,s=signal:s.emit()))
        transfer_buttons.addStretch()
        transfer_layout.addLayout(transfer_buttons)
        self.summary=note('尚未检查 PPT · 本机读取，不激活嵌入对象或外链', True); transfer_layout.addWidget(self.summary)
        buttons=QHBoxLayout(); buttons.addWidget(action('检查 PPTX 中的 Origin 对象',self.choose_ppt))
        self.extract_button=action('完整恢复到新文件夹',self.choose_destination); self.extract_button.setEnabled(False)
        buttons.addWidget(self.extract_button); buttons.addStretch(); transfer_layout.addLayout(buttons)
        self.objects=QTableWidget(0,4); self.objects.setHorizontalHeaderLabels(['所在页','格式','工程大小','状态'])
        self.objects.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.objects.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.objects.setMaximumHeight(180)
        transfer_layout.addWidget(self.objects)
        transfer_layout.addStretch(1)
        group=QGroupBox('读取数据 · OPJ / OPJU'); form=QFormLayout(group)
        data_split=QSplitter(Qt.Orientation.Horizontal);data_split.setChildrenCollapsible(False)
        data_layout.addWidget(data_split,1);data_split.addWidget(group)
        preview_panel=QWidget();preview_layout=QVBoxLayout(preview_panel);preview_layout.setContentsMargins(10,0,0,0)
        data_split.addWidget(preview_panel);data_split.setStretchFactor(1,1);data_split.setSizes([410,650])
        self.source=QLineEdit(); self.source.setPlaceholderText('选择 OPJ / OPJU 或上面恢复出的工程')
        row=QHBoxLayout(); row.addWidget(self.source,1); row.addWidget(action('选择文件',self.choose_origin))
        form.addRow('工程',row)
        self.reader_options=QWidget();reader_form=QFormLayout(self.reader_options);reader_form.setContentsMargins(0,0,0,0)
        self.reader_toggle=QPushButton('读取器设置（按需展开）');self.reader_toggle.setCheckable(True)
        self.reader_toggle.toggled.connect(self.reader_options.setVisible)
        form.addRow(self.reader_toggle);form.addRow(self.reader_options);self.reader_options.hide()
        self.probe=QLineEdit(); default=data_dir()/'origin-evaluation/origin-probe'
        if default.is_file(): self.probe.setText(str(default))
        latest=default.with_name('origin-probe-v10')
        if latest.is_file():self.probe.setText(str(latest))
        probe_row=QHBoxLayout(); probe_row.addWidget(self.probe,1); probe_row.addWidget(action('选择程序',self.choose_probe))
        reader_form.addRow('旧 OPJ 读取器',probe_row)
        self.decoder=QLineEdit(os.environ.get('SPS_OPJU_DECODER',''))
        default_decoder=data_dir()/'origin-evaluation/sch401-opju/opju_decode.py'
        if not self.decoder.text() and default_decoder.is_file():self.decoder.setText(str(default_decoder))
        decoder_row=QHBoxLayout();decoder_row.addWidget(self.decoder,1);decoder_row.addWidget(action('选择模块',self.choose_decoder))
        reader_form.addRow('OPJU 解码模块',decoder_row)
        self.read_button=action('读取数据',self.read_data);self.read_button.setProperty('primary',True);self.read_button.setToolTip('后台读取，并报告未支持列与未知属性');form.addRow(self.read_button)
        self.busyChanged.connect(self.read_button.setDisabled)
        self.coverage=QPlainTextEdit();self.coverage.setReadOnly(True);self.coverage.setMaximumHeight(75)
        self.coverage.setPlaceholderText('读取后显示恢复列、未支持列、元数据未知项；原文件保持不变。')
        form.addRow('能力与完整性',self.coverage)
        self.sheet=QComboBox(); self.x=QComboBox(); self.y=QComboBox()
        for field in (self.sheet,self.x,self.y):
            field.setMinimumContentsLength(10);field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        form.addRow('工作表 / 标识',self.sheet); form.addRow('X 列',self.x); form.addRow('Y 列',self.y)
        self.tables=QTabWidget()
        self.columns_table=QTableWidget(0,5);self.columns_table.setHorizontalHeaderLabels(['列','角色 / 单位','容量','数值 / 缺失 / 文本','逻辑行数'])
        self.preview_table=QTableWidget()
        for table in (self.columns_table,self.preview_table):
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tables.addTab(self.columns_table,'列概览');self.tables.addTab(self.preview_table,'原始值预览')
        self.tables.setToolTip('预览前200行/64列；保存读取结果保留完整原列')
        preview_layout.addWidget(self.tables,1)
        self.use_range=QCheckBox('使用连续行范围');self.use_range.setToolTip('仅重绘所选连续行；完整原列保留在读取结果中')
        self.row_start=QSpinBox();self.row_stop=QSpinBox()
        for spin in (self.row_start,self.row_stop):spin.setRange(1,2_000_000);spin.setEnabled(False)
        preview_layout.addWidget(self.use_range)
        self.range_row=QHBoxLayout();self.range_row.addWidget(note('首行'));self.range_row.addWidget(self.row_start);self.range_row.addWidget(note('末行'));self.range_row.addWidget(self.row_stop)
        preview_layout.addLayout(self.range_row)
        self.xlabel=QLineEdit('X'); self.ylabel=QLineEdit('Y')
        form.addRow('X 轴含义/单位',self.xlabel); form.addRow('Y 轴含义/单位',self.ylabel)
        pair_buttons=QHBoxLayout(); pair_buttons.addWidget(action('添加 X/Y 配对',self.add_pair))
        pair_buttons.addWidget(action('清空选择',self.clear_pairs)); pair_buttons.addStretch(); self.reconstruct_button=action('生成可编辑图形',self.reconstruct);self.reconstruct_button.setProperty('primary',True);self.reconstruct_button.setEnabled(False)
        # Pair actions stay adjacent to the preview at normal laptop sizes.
        preview_layout.addLayout(pair_buttons);preview_layout.addWidget(self.reconstruct_button)
        self.details=QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(70);self.details.setPlaceholderText('所选 X/Y 配对将在这里列出。');preview_layout.addWidget(self.details)
        data_layout.addWidget(HelpDisclosure('OPJU仅支持已验证的数据子集；未知列、单位和角色明确报告。普通图像不含科研数据。预览只显示前200行/64列，另存读取结果保留完整原列。','数据与预览说明'))
        self.save_button=action('保存完整读取结果…',self.save_recovery);self.save_button.setToolTip('包含科研原始数值、缺失位置与未支持项');self.save_button.setEnabled(False);preview_layout.addWidget(self.save_button)
        self.status=note('请选择工程文件并读取数据');self.status.setProperty('status',True);layout.addWidget(self.busy_indicator);layout.addWidget(self.status)
        self.sheet.currentIndexChanged.connect(self.show_columns)
        self.objects.cellClicked.connect(self.select_object)
        self.source.textChanged.connect(self.invalidate_data)
        self.probe.textChanged.connect(self.invalidate_data)
        self.decoder.textChanged.connect(self.invalidate_data)
        self.use_range.toggled.connect(self.range_changed)
        self.row_start.valueChanged.connect(self.clear_pairs)
        self.row_stop.valueChanged.connect(self.clear_pairs)
    def invalidate_data(self):
        self.input_generation+=1
        self.recovery=None; self.sheet.clear(); self.x.clear(); self.y.clear(); self.clear_pairs()
        self.coverage.clear();self.columns_table.setRowCount(0);self.preview_table.setRowCount(0)
        self.save_button.setEnabled(False)
        self.xlabel.setText('X');self.ylabel.setText('Y')
    def choose_ppt(self):
        path,_=QFileDialog.getOpenFileName(self,'检查 PPTX','','PowerPoint (*.pptx)')
        if path:self.scan(path)
    def scan(self,path):
        self.sections.setCurrentIndex(1)
        if self.busy:self.status.setText('上一项读取仍在执行。');return
        self.ppt=Path(path); self.recovered_dir=None
        self.work(lambda:office.scan(path),self.set_report)
    def set_report(self,report):
        self.report=report; c=report['counts']
        self.summary.setText(f"Origin 对象 {c['origin_objects']} · OPJ {c['opj']} · OPJU {c['opju']} · 外链 {c['external_links']}")
        self.objects.setRowCount(len(report['objects']))
        for i,item in enumerate(report['objects']):
            pages=', '.join(str(u['slide']) for u in item['uses']) or '未引用部件'
            for j,value in enumerate((pages,item['format'].upper(),f"{item['bytes']:,} B",'可选 OPJ 数据读取' if item['format']=='opj' else '可提取后尝试部分解码')):
                self.objects.setItem(i,j,QTableWidgetItem(value))
        self.extract_button.setEnabled(bool(report['objects'])); self.status.setText('检查完成；尚未写入恢复文件。')
    def choose_destination(self):
        parent=QFileDialog.getExistingDirectory(self,'选择恢复目录的父文件夹')
        if not parent:return
        from PySide6.QtWidgets import QInputDialog
        name,ok=QInputDialog.getText(self,'新恢复目录','新目录名',text='SPS-Origin-recovered')
        if ok and name and Path(name).name==name and name not in ('.','..'):
            self.extract_to(Path(parent)/name)
    def extract_to(self,destination):
        source=self.ppt; destination=Path(destination)
        def done(report):
            self.set_report(report); self.recovered_dir=destination
            self.status.setText(f'已完整提取 {len(report["objects"])} 个对象，原 PPT 未修改；点击列表中的 OPJ / OPJU 再读取列。')
        self.work(lambda:office.extract(source,destination),done)
    def select_object(self,row,column=0):
        if self.report and self.recovered_dir:
            self.sections.setCurrentIndex(0)
            item=self.report['objects'][row]; self.source.setText(str(self.recovered_dir/item['file']))
            self.status.setText('已选择 OPJU；可后台部分读取。未支持编码不能读取，不代表完整工程恢复。' if item['format']=='opju' else '已选择旧 OPJ；点击读取列信息。')
    def choose_origin(self):
        path,_=QFileDialog.getOpenFileName(self,'读取 Origin 数据','','Origin (*.opj *.opju)')
        if path:self.importRequested.emit(path)
    def choose_probe(self):
        path,_=QFileDialog.getOpenFileName(self,'选择独立 OPJ 读取器')
        if path:self.probe.setText(path)
    def choose_decoder(self):
        path,_=QFileDialog.getOpenFileName(self,'选择经摘要核验的 OPJU 解码模块','','Python (*.py)')
        if path:self.decoder.setText(path)
    def range_changed(self,enabled):
        self.row_start.setEnabled(enabled);self.row_stop.setEnabled(enabled);self.clear_pairs()
    def selected_range(self):
        return [self.row_start.value()-1,self.row_stop.value()] if self.use_range.isChecked() else None
    def read_data(self):
        if self.busy:self.status.setText('上一项读取仍在执行。');return
        source,probe,decoder=self.source.text(),self.probe.text(),self.decoder.text()
        generation=self.input_generation
        def done(recovery):
            if self.input_generation!=generation:
                self.status.setText('读取期间文件或读取器选择已变化，未采用旧结果。');return
            self.set_recovery(recovery)
        self.work(lambda:origin_data.read_any(source,probe or None,decoder or None),done)
    def set_recovery(self,recovery):
        self.recovery=recovery; self.save_button.setEnabled(True); self.clear_pairs(); self.sheet.clear()
        if recovery.get('schema')=='sps.origin-data/1':
            raw=recovery['raw'];counts=raw.get('counts',{})
            total=sum(len(s['columns']) for s in recovery['spreadsheets'])
            rejected=raw.get('rejected',[])
            lines=[f"{recovery['format'].upper()} · 部分数据读取 · {total} 列恢复 · {len(rejected)} 列未支持"]
            if recovery['format']=='opju':lines.append(f"列属性确认 {counts.get('metadata_all',counts.get('metadata',0))} / {total}；完整存储容量保留，不按逻辑行数截断。")
            lines+=recovery.get('warnings',[])
            lines += [f"未支持 {r.get('dataset','?')}：{r.get('reason','未知')}" for r in rejected]
            self.coverage.setPlainText('\n'.join(lines))
        else:self.coverage.setPlainText('旧 OPJ 部分数据读取；完整图形、原始模板及公式不恢复。')
        for i,sheet in enumerate(origin_data.sheets(recovery)):
            from .origin import raw_text
            self.sheet.addItem(raw_text(sheet.get('name_hex','')) or f'工作表 {i+1}',i)
        self.show_columns(); self.status.setText('数据已读出；显式选择 X/Y 与可选连续行，轴含义/单位请核实填写。')
    def show_columns(self):
        self.x.clear(); self.y.clear();self.columns_table.setRowCount(0);self.preview_table.setRowCount(0)
        if self.recovery is None or self.sheet.currentData() is None:return
        from .origin import raw_text
        sheet=origin_data.sheets(self.recovery)[self.sheet.currentData()]
        self.columns_table.setRowCount(len(sheet['columns']))
        for i,column in enumerate(sheet['columns']):
            name=raw_text(column.get('name_hex','')) or f'列 {i+1}'
            role={0:'X',1:'Y'}.get(column.get('type_raw'),'未知 / 未映射')
            text=f"{name} · {len(column['data'])} 行 · 源角色 {role}"
            self.x.addItem(text,i); self.y.addItem(text,i)
            values=column['data'];numeric=sum(type(v)in(int,float) and math.isfinite(v) for v in values)
            missing=sum(v is None for v in values);text_count=sum(isinstance(v,str)for v in values)
            unit=column.get('units');unit='未知' if unit is None else (unit or '未指定')
            logical=column.get('logical_rows');logical='未知' if logical is None else str(logical)
            for j,value in enumerate((name,f'{role} / {unit}',str(len(values)),f'{numeric} / {missing} / {text_count}',logical)):
                self.columns_table.setItem(i,j,QTableWidgetItem(value))
        columns=sheet['columns'][:64];rows=min(200,max((len(c['data'])for c in columns),default=0))
        self.preview_table.setColumnCount(len(columns));self.preview_table.setRowCount(rows)
        self.preview_table.setHorizontalHeaderLabels([raw_text(c.get('name_hex',''))for c in columns])
        for ci,column in enumerate(columns):
            for ri in range(rows):
                if ri>=len(column['data']):value='[超出列容量]'
                else:
                    v=column['data'][ri];value='[缺失]' if v is None else str(v)
                self.preview_table.setItem(ri,ci,QTableWidgetItem(value))
        if not self.pairs:
            self.row_start.setValue(1);self.row_stop.setValue(max((len(c['data'])for c in sheet['columns']),default=1)or 1)
        self.x.setCurrentIndex(-1); self.y.setCurrentIndex(-1)
    def clear_pairs(self,*args):
        self.pairs=[];self.details.setPlainText('尚未添加 X/Y 配对')
        if hasattr(self,'reconstruct_button'):self.reconstruct_button.setEnabled(False)
    def add_pair(self):
        def run():
            mapping=[self.sheet.currentData(),self.x.currentData(),self.y.currentData()]
            origin_data.reconstruct(self.recovery,[mapping],row_range=self.selected_range())
            if mapping not in self.pairs:self.pairs.append(mapping)
            self.reconstruct_button.setEnabled(bool(self.pairs))
            self.details.setPlainText('\n'.join(f'表 {s} → X 列 {x} / Y 列 {y} · 行 {self.row_start.value()}–{self.row_stop.value()}' if self.use_range.isChecked() else f'表 {s} → X 列 {x} / Y 列 {y} · 完整原列' for s,x,y in self.pairs))
        self.guarded(run)
    def reconstruct(self):
        self.guarded(lambda:self.projectReady.emit(origin_data.reconstruct(
            self.recovery,self.pairs,self.xlabel.text(),self.ylabel.text(),row_range=self.selected_range())))
    def save_recovery(self):
        if self.recovery is None:self.status.setText('请先读取工程。');return
        path,_=QFileDialog.getSaveFileName(self,'保存完整读取器输出（含科研数据）','origin-data.json','JSON (*.json)')
        if path:
            def run():
                if Path(path).exists():raise ValueError('同名输出已存在，请换名')
                write_json(path,self.recovery)
            self.guarded(run)
