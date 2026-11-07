"""Origin inspection and AI request workspaces. Background work never edits a project."""
from __future__ import annotations
import copy
import json
from .local_paths import data_dir
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor,QFontDatabase
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,
                              QPushButton,QPlainTextEdit,QComboBox,QGroupBox,QTableWidget,
                              QTableWidgetItem,QFileDialog,QHeaderView,QCheckBox,QSpinBox,
                              QSplitter,QAbstractItemView,QTabWidget,QProgressBar)
from . import ai,origin
from .model import read_json,write_json
from .template_ui import note
from .ui_helpers import HelpDisclosure


class Task(QThread):
    succeeded=Signal(object)
    failed=Signal(str)
    def __init__(self,fn,parent=None):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.succeeded.emit(self.fn())
        except Exception as e:self.failed.emit(str(e))


class WorkPanel(QWidget):
    busyChanged=Signal(bool)
    def __init__(self,parent=None):
        super().__init__(parent);self.tasks=[]
        self.busy_indicator=QProgressBar(self);self.busy_indicator.setRange(0,0)
        self.busy_indicator.setTextVisible(False);self.busy_indicator.setFixedHeight(4);self.busy_indicator.hide()
        self.busyChanged.connect(self.busy_indicator.setVisible)
    @property
    def busy(self):return any(t.isRunning() for t in self.tasks)
    def work(self,fn,done):
        if self.busy:self.status.setText('上一项任务仍在执行，请等待结果。');return
        task=Task(fn,self);self.tasks.append(task)
        task.succeeded.connect(lambda result:self.guarded(lambda:done(result)))
        task.failed.connect(lambda msg:self.status.setText('未完成：'+msg))
        task.finished.connect(lambda t=task:self.finish(t))
        self.status.setText('正在处理…界面仍可操作；不会自动修改工程。')
        self.busyChanged.emit(True)
        task.start()
    def finish(self,task):
        if task in self.tasks:self.tasks.remove(task)
        self.busyChanged.emit(self.busy)
        task.deleteLater()
    def guarded(self,fn):
        try:return fn()
        except Exception as e:self.status.setText('未完成：'+str(e));return None


def action(text,fn):
    button=QPushButton(text);button.clicked.connect(fn);return button


class OriginPanel(WorkPanel):
    styleRequested=Signal(object)
    templateRequested=Signal(object)
    referenceSelected=Signal(object)
    observationsSelected=Signal(object)
    def __init__(self,settings_path,parent=None):
        super().__init__(parent)
        self.settings_path=Path(settings_path);self.report=None
        layout=QVBoxLayout(self);layout.setContentsMargins(18,16,18,14)
        title=note('Origin 风格分析与迁移',True);title.setObjectName('workspace_title');layout.addWidget(title)
        layout.addWidget(note('分析旧 OPJ 样式；OPJU 数据请到「数据与 Office」。'))
        reader=QGroupBox('可选读取器');form=QFormLayout(reader)
        self.probe=QLineEdit();self.probe.setPlaceholderText('独立 OPJ 探针程序路径')
        default=data_dir()/'origin-evaluation/origin-probe'
        if default.is_file():self.probe.setText(str(default))
        try:
            if self.settings_path.exists():self.probe.setText(read_json(self.settings_path)['probe'])
        except Exception:pass
        row=QHBoxLayout();row.addWidget(self.probe,1);row.addWidget(action('选择程序',self.choose_probe))
        form.addRow('读取程序',row);layout.addWidget(reader)
        buttons=QHBoxLayout();self.analyze_button=action('分析旧 OPJ',self.choose_file);self.analyze_button.setProperty('primary',True)
        self.busyChanged.connect(self.analyze_button.setDisabled)
        buttons.addWidget(self.analyze_button);buttons.addWidget(action('汇总样本文件夹',self.choose_folder));buttons.addWidget(action('保存分析报告',self.save_report));buttons.addStretch();layout.addLayout(buttons)
        self.counts=note('选择旧 OPJ 或样本文件夹开始分析');layout.addWidget(self.counts)
        self.layer=QComboBox();self.layer.setMinimumContentsLength(18);self.layer.currentIndexChanged.connect(self.show_layer)
        layout.addWidget(self.layer)
        split=QSplitter(Qt.Orientation.Vertical)
        self.mapping=QTableWidget(0,5);self.mapping.setHorizontalHeaderLabels(['源曲线','图型','颜色','线宽观测','映射情况'])
        self.mapping.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mapping.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.mapping.verticalHeader().hide()
        self.mapping.setMinimumHeight(120);split.addWidget(self.mapping)
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);self.summary.setPlaceholderText('分析后显示观测频率、未支持对象与转换边界。')
        split.addWidget(self.summary);split.setSizes([190,320]);layout.addWidget(split,1)
        buttons=QHBoxLayout()
        self.transfer_button=action('审查所选层风格',self.transfer)
        self.template_button=action('加入模板库（部分模板）',self.make_template)
        self.reference_button=action('作为 AI 风格参考',self.select_reference)
        for b in (self.transfer_button,self.template_button,self.reference_button):buttons.addWidget(b);b.setEnabled(False)
        buttons.addStretch();layout.addLayout(buttons)
        self.status=note('分析和迁移在本机进行；图形保真尚需 Origin 原图对照。');self.status.setProperty('status',True);layout.addWidget(self.busy_indicator);layout.addWidget(self.status)
        self.probe.textChanged.connect(self.reader_changed)
    def reader_changed(self):
        if self.busy:return
        self.guarded(lambda:write_json(self.settings_path,{'probe':self.probe.text()}))
    def choose_probe(self):
        path,_=QFileDialog.getOpenFileName(self,'选择独立 OPJ 读取程序')
        if path:self.probe.setText(path)
    def choose_file(self):
        path,_=QFileDialog.getOpenFileName(self,'分析旧 OPJ 样式','','旧版 Origin (*.opj)')
        if path:self.inspect_file(path)
    def inspect_file(self,path):
        probe=self.probe.text().strip()
        self.work(lambda:origin.inspect(path,probe),self.set_report)
    def choose_folder(self):
        directory=QFileDialog.getExistingDirectory(self,'选择 Origin 样本文件夹')
        if directory:self.inspect_folder(directory)
    def inspect_folder(self,directory):
        paths=[p for p in Path(directory).rglob('*') if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.opj','.opju','.otp','.otpu','.oth')]
        if not paths:self.status.setText('该文件夹没有 Origin 工程或模板。');return
        if len(paths)>100:self.status.setText('一次最多分析 100 份；请缩小文件夹范围。');return
        probe=self.probe.text().strip()
        self.work(lambda:origin.profile(paths,probe),self.set_report)
    def set_report(self,report):
        self.report=origin.validate_report(report)
        self.layer.blockSignals(True);self.layer.clear()
        analyses=report['analyses'] if report['schema']==origin.PROFILE_SCHEMA else [report]
        for analysis in analyses:
            for layer in analysis['layers']:
                self.layer.addItem(f"{analysis['source']['name']} · {layer['graph_name']} · 层 {layer['layer_index']+1}",(analysis,layer['id']))
        self.layer.blockSignals(False)
        count=report['counts']
        prefix=f"文件 {count['analyzed']} / {count['files']} 部分可读 · " if report['schema']==origin.PROFILE_SCHEMA else ''
        self.counts.setText(prefix+f"{count['graphs']} 图形 · {count['layers']} 图层 · {count['curves']} 曲线")
        self.summary.setPlainText(origin.markdown(report));self.show_layer()
        self.observationsSelected.emit(origin.style_observations(report))
        self.status.setText('分析完成 · 观测统计有明确分母；未识别字段保持或列明，不推断个人偏好。')
    def selected(self):
        value=self.layer.currentData()
        if not value:raise ValueError('请先分析并选择图层')
        return value
    def show_layer(self):
        value=self.layer.currentData();self.mapping.setRowCount(0)
        for b in (self.transfer_button,self.template_button,self.reference_button):b.setEnabled(bool(value))
        if not value:return
        report,ident=value;layer=next(l for l in report['layers'] if l['id']==ident)
        self.mapping.setRowCount(len(layer['curves']))
        for i,curve in enumerate(layer['curves']):
            style=curve['style'];values=[str(i+1),curve['plot_type'],style.get('color','未识别'),str(style.get('width','未映射')),
                                         '部分映射' if style else '不迁移']
            for j,value in enumerate(values):
                item=QTableWidgetItem(value);item.setToolTip('\n'.join(curve['issues']+layer['issues']))
                if j==2 and 'color' in style:item.setForeground(QColor(style['color']))
                self.mapping.setItem(i,j,item)
    def transfer(self):
        def run():
            style=origin.layer_style(*self.selected());self.referenceSelected.emit(style);self.styleRequested.emit(style)
        self.guarded(run)
    def select_reference(self):
        def run():
            self.referenceSelected.emit(origin.layer_style(*self.selected()));self.status.setText('所选层已作为 AI 样式参考；只含已识别格式，不含源数据。')
        self.guarded(run)
    def make_template(self):self.guarded(lambda:self.templateRequested.emit(origin.layer_template(*self.selected())))
    def save_report(self):
        if self.report is None:self.status.setText('请先分析工程。');return
        path,_=QFileDialog.getSaveFileName(self,'保存分析报告','origin-analysis.json','JSON (*.json)')
        if path:self.guarded(lambda:self.save_to(path))
    def save_to(self,path):
        path=Path(path);md=path.with_suffix('.md')
        # Both helpers protect existing files; markdown is never written over source.
        if path.exists() or md.exists():raise ValueError('同名报告或总结已存在，请换名保存')
        write_json(path,self.report)
        md.write_text(origin.markdown(self.report));self.status.setText('已保存 JSON 分析与 Markdown 总结。')


class AIPanel(WorkPanel):
    planReady=Signal(object)
    def __init__(self,project_getter,settings_path,parent=None):
        super().__init__(parent)
        self.project_getter=project_getter;self.settings_path=Path(settings_path)
        self.prepared=None;self.plan=None;self.reference=None;self.observations=None;self.key_env='SPS_AI_API_KEY';self.timeout_seconds=30
        layout=QVBoxLayout(self);layout.setContentsMargins(18,16,18,14)
        title=note('AI 风格助手',True);title.setObjectName('workspace_title');layout.addWidget(title)
        layout.addWidget(note('先核对待发送内容，再获取建议；应用前始终需要审查。'))
        content=QSplitter(Qt.Orientation.Horizontal);content.setChildrenCollapsible(False);layout.addWidget(content,1)
        settings_panel=QWidget();settings_layout=QVBoxLayout(settings_panel);settings_layout.setContentsMargins(0,0,10,0)
        settings_panel.setMinimumWidth(300);settings_panel.setMaximumWidth(430);content.addWidget(settings_panel)
        task_panel=QWidget();task_layout=QVBoxLayout(task_panel);task_layout.setContentsMargins(10,0,0,0);content.addWidget(task_panel)
        content.setStretchFactor(1,1);content.setSizes([360,740])
        group=QGroupBox('服务配置 · 密钥仅本次会话使用');form=QFormLayout(group)
        self.base=QLineEdit('http://127.0.0.1:11434/v1');self.model=QLineEdit();self.model.setPlaceholderText('填写服务提供的模型名称')
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('可选；也可使用 SPS_AI_API_KEY 环境变量，不保存密钥')
        self.json_mode=QCheckBox('请求 JSON 模式');self.json_mode.setToolTip('不支持时可取消；返回内容仍会严格校验');self.json_mode.setChecked(True)
        self.tokens=QSpinBox();self.tokens.setRange(256,8192);self.tokens.setValue(2048)
        form.addRow('服务地址',self.base);form.addRow('模型',self.model);form.addRow('API 密钥',self.key)
        form.addRow('输出上限',self.tokens);form.addRow(self.json_mode);settings_layout.addWidget(group)
        controls=QVBoxLayout();controls.addWidget(action('保存服务配置',self.save_config));controls.addWidget(action('载入配置',self.load_config_dialog));controls.addWidget(action('导出配置',self.export_config));settings_layout.addLayout(controls)
        self.reference_note=note('风格参考：未选择；可在 Origin 样式页选取图层。');settings_layout.addWidget(self.reference_note)
        self.observations_note=note("参考统计：未选取；可在 Origin 样式页汇总样本。");settings_layout.addWidget(self.observations_note)
        settings_layout.addStretch(1)
        task_layout.addWidget(note('描述样式要求'))
        self.prompt=QLineEdit();self.prompt.setPlaceholderText('例如：统一配色和线宽，保持原始数据不变');task_layout.addWidget(self.prompt)
        self.views=QTabWidget()
        self.views.setMinimumHeight(140)
        self.views.setStyleSheet("QTabBar::tab { padding:7px 12px; }")
        self.outgoing=QPlainTextEdit();self.outgoing.setProperty("code",True);self.outgoing.setReadOnly(True);self.outgoing.setPlaceholderText('生成后在这里检查完整待发送内容。不会上传原始数值、标题/单位、数据源、路径或审计。')
        self.outgoing.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.views.addTab(self.outgoing,"待发送信息")
        self.result=QPlainTextEdit();self.result.setReadOnly(True);self.result.setPlaceholderText('建议、使用量与执行边界将在这里显示。')
        self.views.addTab(self.result,"建议与使用量");task_layout.addWidget(self.views,1)
        requests=QHBoxLayout();requests.addWidget(action('查看待发送样式',self.prepare_request))
        self.send_button=action('发送请求（可能计费）',self.send);self.send_button.setProperty('primary',True);self.send_button.setEnabled(False);requests.addWidget(self.send_button);requests.addStretch()
        task_layout.addLayout(requests)
        self.consent=QCheckBox('我确认将上方内容发送到所填服务');self.consent.toggled.connect(self.update_send);task_layout.addWidget(self.consent)
        local_group=QGroupBox('离线规则 · 直接进入审查');local=QHBoxLayout(local_group)
        local.addWidget(action('统一线宽',lambda:self.offline('uniform')))
        local.addWidget(action('参考所选风格',lambda:self.offline('reference')));settings_layout.insertWidget(2,local_group)
        task_layout.addWidget(action('保存建议与审查计划',self.save_plan))
        self.status=note('尚未请求 · 离线规则可立即执行，不调用模型或付费接口。');self.status.setProperty('status',True);layout.addWidget(self.busy_indicator);layout.addWidget(self.status)
        for field in (self.base,self.model,self.prompt):field.textChanged.connect(self.invalidate)
        self.json_mode.toggled.connect(self.invalidate);self.tokens.valueChanged.connect(self.invalidate)
        try:
            if self.settings_path.exists():self.set_config(ai.config_from_dict(read_json(self.settings_path)))
        except Exception:self.status.setText('已有服务配置无效，请重新填写；未读取或发送密钥。')
    def config(self):
        return ai.AIConfig(base_url=self.base.text().strip(),model=self.model.text().strip(),json_mode=self.json_mode.isChecked(),max_tokens=self.tokens.value(),api_key_env=self.key_env,timeout_seconds=self.timeout_seconds).validate()
    def set_config(self,config):
        self.key_env=config.api_key_env;self.timeout_seconds=config.timeout_seconds
        self.key.setPlaceholderText(f"可选；或使用 {self.key_env} 环境变量，不保存密钥")
        self.base.setText(config.base_url);self.model.setText(config.model);self.json_mode.setChecked(config.json_mode);self.tokens.setValue(config.max_tokens)
        self.invalidate()
    def invalidate(self,*args):
        self.prepared=None;self.plan=None;self.send_button.setEnabled(False);self.consent.setChecked(False)
        self.outgoing.clear()
    def set_observations(self,value):
        self.observations=ai.validate_observations(value)
        c=value['counts']
        self.observations_note.setText(f"参考统计：{c.get('graphs',0)} 图形 / {c.get('curves',0)} 曲线；待发送内容包含匿名频率，不含文件名。")
        self.invalidate()
    def set_reference(self,style):
        self.reference=copy.deepcopy(style);self.reference_note.setText('风格参考：'+style.get('name','已选取部分风格'));self.invalidate()
    def prepare_request(self):
        def run():
            self.prepared=ai.prepare(self.project_getter().clone(),self.prompt.text(),self.config(),self.reference,self.observations)
            self.outgoing.setPlainText(json.dumps({'endpoint':self.prepared['endpoint'],'body':self.prepared['body'],'privacy':self.prepared['privacy']},ensure_ascii=False,indent=2))
            self.views.setCurrentWidget(self.outgoing)
            self.consent.setChecked(False);self.status.setText('待发送信息已生成；请核对服务、模型和内容。尚未联网。')
        self.guarded(run)
    def update_send(self):self.send_button.setEnabled(self.prepared is not None and self.consent.isChecked() and not self.busy)
    def send(self):
        if self.prepared is None or not self.consent.isChecked():self.status.setText('请先查看并确认待发送内容。');return
        def run():
            snapshot=self.project_getter().clone();config=self.config();prepared=copy.deepcopy(self.prepared)
            ai.validate_prepared(snapshot,prepared,config)
            key=self.key.text() or None
            self.send_button.setEnabled(False);self.consent.setChecked(False)
            self.work(lambda:ai.request_plan(snapshot,prepared,config,key,render_check=False),lambda plan:self.receive_network(plan,prepared['body_sha256']))
            self.key.clear()
        self.guarded(run)
    def receive_network(self,plan,request_hash):
        if self.prepared is None or self.prepared['body_sha256']!=request_hash:
            self.status.setText('请求期间输入已变化，返回结果未采用；请重新查看待发送内容。');return
        self.receive(plan)
    def receive(self,plan):
        if plan['base_hash']!=self.project_getter().fingerprint():
            self.status.setText('工程已变化，建议已过期；请重新请求。');return
        if plan['review']:
            # Matplotlib's rc state is process-global: render on the UI thread,
            # after background HTTP/model validation, never concurrently with Qt painting.
            from .render import preflight
            from .commands import run_operations
            preflight(run_operations(self.project_getter(),plan['review']['operations']),100)
        self.plan=plan
        provider=plan['provider'];kind='离线规则（非模型输出）' if provider.get('mode')=='offline_rules' else 'AI 建议（需审查）'
        self.result.setPlainText(kind+'\n\n'+plan['summary']+'\n\n'+'\n'.join(plan['warnings'])+'\n\n使用量：'+json.dumps(plan.get('usage',{}),ensure_ascii=False))
        self.views.setCurrentWidget(self.result)
        self.status.setText('建议已生成，前往“风格审查”核对并应用。' if plan['review'] else '已生成总结；没有修改操作。')
        self.planReady.emit(plan)
    def offline(self,mode):
        self.invalidate()
        self.guarded(lambda:self.receive(ai.offline_plan(self.project_getter().clone(),mode,self.reference)))
    def save_config(self):self.guarded(lambda:write_json(self.settings_path,self.config().to_dict()))
    def load_config_dialog(self):
        path,_=QFileDialog.getOpenFileName(self,'载入 AI 配置','','JSON (*.json)')
        if path:self.guarded(lambda:self.set_config(ai.config_from_dict(read_json(path))))
    def export_config(self):
        path,_=QFileDialog.getSaveFileName(self,'导出不含密钥的配置','ai-config.json','JSON (*.json)')
        if path:self.guarded(lambda:write_json(path,self.config().to_dict()))
    def save_plan(self):
        if not self.plan:self.status.setText('尚无建议可保存。');return
        path,_=QFileDialog.getSaveFileName(self,'保存 AI 建议','ai-plan.json','JSON (*.json)')
        if path:self.guarded(lambda:write_json(path,self.plan))
