"""Explicit axis-side editor and reviewable journal typography dialog."""
import io
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QCheckBox,QPushButton,
 QDialogButtonBox,QComboBox,QFormLayout,QPlainTextEdit,QProgressBar,QSplitter)
from .publication import PROFILES,VERIFIED,effective_sides,framed_sides,operation,inspect_pages
from .widgets import AspectPreview
from .workflow_ui import Task


class AxesDialog(QDialog):
    def __init__(self,figure,parent=None):
        super().__init__(parent);self.setWindowTitle('四边轴 · 框线、刻度和数字');self.resize(560,330)
        layout=QVBoxLayout(self);grid=QGridLayout();layout.addLayout(grid);self.fields={}
        for j,name in enumerate(('轴边','框线','刻度短线','刻度数字')):grid.addWidget(QLabel(name),0,j)
        for i,(side,title)in enumerate((('bottom','下 X'),('top','上 X'),('left','左 Y'),('right','右 Y')),1):
            grid.addWidget(QLabel(title),i,0);self.fields[side]={}
            for j,(key,value)in enumerate(effective_sides(figure)[side].items(),1):
                field=QCheckBox();field.setChecked(value);field.setAccessibleName(title+' '+key);grid.addWidget(field,i,j);self.fields[side][key]=field
        preset=QPushButton('四边框 · 仅左下刻度');preset.clicked.connect(self.set_framed);layout.addWidget(preset)
        note=QLabel('上/下共享当前 X 比例，左/右共享当前 Y 比例；独立双轴请分别选择原图层。');note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
    def set_framed(self):
        for side,settings in framed_sides().items():
            for key,value in settings.items():self.fields[side][key].setChecked(value)
    def settings(self):return {side:{key:field.isChecked()for key,field in settings.items()}for side,settings in self.fields.items()}


class PublicationDialog(QDialog):
    """Preview sealed transactions; changing parameters invalidates approval."""
    def __init__(self,session,preferences=None,parent=None,batch=False):
        super().__init__(parent);self.session=session;self.batch=batch;self.plan=None;self.task=None
        self.setWindowTitle('期刊规范 · 批量统一坐标轴与字体');self.resize(1050,730)
        prefs=preferences or {};layout=QVBoxLayout(self);split=QSplitter();layout.addWidget(split,1)
        from PySide6.QtWidgets import QWidget
        controls=QWidget();form=QFormLayout(controls);split.addWidget(controls)
        self.profile=QComboBox()
        for key,preset in PROFILES.items():self.profile.addItem(preset['name'],key)
        self.profile.setCurrentIndex(max(0,self.profile.findData(prefs.get('profile','nature'))))
        self.size=QComboBox();self.size.addItem('单栏','single');self.size.addItem('双栏','double');self.size.setCurrentIndex(prefs.get('size')=='double')
        self.scope=QComboBox();self.scope.addItem('当前图页 · 全部图层','page');self.scope.addItem('工程所有图页','all');self.scope.setCurrentIndex(1)
        if batch:self.scope.setEnabled(False)
        self.font=QComboBox();self.font.setEditable(True)
        from matplotlib.font_manager import fontManager
        names=sorted({f.name for f in fontManager.ttflist});self.font.addItems(names)
        self.font.setCurrentText(prefs.get('font','Arial'if 'Arial'in names else'DejaVu Sans'))
        form.addRow('期刊 / 出版商',self.profile);form.addRow('最终栏宽',self.size);form.addRow('处理范围',self.scope);form.addRow('明确使用字体',self.font)
        self.auto=QCheckBox('以后导入 Origin 自动应用此设置');self.auto.setChecked(prefs.get('enabled',False));form.addRow(self.auto)
        self.rules=QLabel();self.rules.setWordWrap(True);self.rules.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction);self.rules.setOpenExternalLinks(True);form.addRow(self.rules)
        note=QLabel('保留数据、范围、曲线颜色和线型。单主图层四边框、左下刻度；实际双轴/多层图保留轴侧和位置，另标待检查。长标签换行，不降低规范字号。');note.setWordWrap(True);form.addRow(note)
        self.preview_button=QPushButton('生成预览与逐页检查');self.preview_button.clicked.connect(self.preview);form.addRow(self.preview_button)
        right=QWidget();right_layout=QVBoxLayout(right);split.addWidget(right)
        self.image=AspectPreview('当前图页预览');self.image.setMinimumSize(340,230);right_layout.addWidget(self.image,1)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);right_layout.addWidget(self.report,1)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();layout.addWidget(self.progress)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.apply=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.apply.setText('按所选规范批量处理文件…'if batch else'应用已预览设置');self.apply.setEnabled(False)
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        for w in(self.profile,self.size,self.scope,self.font):w.currentIndexChanged.connect(self.invalidate)
        self.font.editTextChanged.connect(self.invalidate);self.invalidate()
    def options(self):return {'profile':self.profile.currentData(),'size':self.size.currentData(),'font':self.font.currentText(),'scope':self.scope.currentData()}
    def preferences(self):return dict(self.options(),enabled=self.auto.isChecked())
    def invalidate(self,*args):
        # Editable native combo boxes may emit a duplicate change on focus loss.
        # Only a real option change invalidates the sealed preview.
        if self.plan is not None and self.options()==getattr(self,'_preview_options',None):return
        self.plan=None;self.apply.setEnabled(False);self.image.clear()
        p=PROFILES[self.profile.currentData()];width=p['widths'][self.size.currentData()=='double']
        self.rules.setText(f"<b>官方依据（核对 {VERIFIED}）</b><br>{p['official']}<br><br><b>本次预设：{width:.2f} mm · {p['font_size']} pt</b><br>{p['choices']}<br><a href='{p['source']}'>查看官方指南</a>")
        self.report.setPlainText('先预览，再应用。预设不能代替投稿前人工检查。')
    def preview(self):
        if self.task:return
        from .commands import run_operations
        from .render import draw
        options=self.options()
        try:
            plan=self.session.preview([operation(**options)])
            project=run_operations(self.session.project,plan['operations'])
        except Exception as error:
            self.report.setPlainText('预览未完成：'+str(error));return
        self.progress.show();self.preview_button.setEnabled(False)
        def work():
            checks=inspect_pages(project);fig,*_=draw(project,dpi=120);buf=io.BytesIO();fig.savefig(buf,format='png',dpi=120)
            return checks,buf.getvalue()
        task=Task(work,self);self.task=task
        def done(result):
            if self.options()!=options:return
            checks,data=result;pix=QPixmap();pix.loadFromData(data);self.image.setPixmap(pix)
            self._preview_options=options;self.plan=plan;self.apply.setEnabled(True)
            self.report.setPlainText(f"预览：{len(plan['changes'])} 处文档变化；{len(checks)} 图页。\n"+'\n'.join(('✓ 'if c['passed']else'待检查 ')+c['name']+(': '+c['error']if c['error']else'：文字边界/刻度检查通过')for c in checks)+('\n\n'+ '\n'.join(c['name']+'：'+note for c in checks for note in c.get('notes',[])) if any(c.get('notes')for c in checks)else '')+'\n\n图例遮挡、数据语义和配色仍需逐图检查；不自动修改曲线。')
        def failed(message):self.report.setPlainText('预览未完成：'+message)
        def finished():self.task=None;self.progress.hide();self.preview_button.setEnabled(True);task.deleteLater()
        task.succeeded.connect(done);task.failed.connect(failed);task.finished.connect(finished);task.start()
    def reject(self):
        if self.task:self.report.setPlainText('预览正在结束，请等待完成后关闭。');return
        super().reject()
    def closeEvent(self,event):
        if self.task:event.ignore()
        else:super().closeEvent(event)
