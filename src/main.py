import ctypes
from ctypes import wintypes
from collections import deque
from datetime import datetime
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import (Qt, QTimer, QThread, Signal, QObject, QByteArray,
                            QBuffer, QIODevice, QRect, QPoint, QSize,
                            QAbstractNativeEventFilter, QLockFile, QDir)
from PySide6.QtGui import (QColor, QPainter, QPen, QPixmap, QImage, QFont,
                           QIcon, QShortcut, QKeySequence, QAction)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
    QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QSplitter, QPlainTextEdit,
    QFileDialog, QListWidget, QListWidgetItem, QCheckBox, QMenu,
    QSystemTrayIcon, QProgressBar, QComboBox)
from core import OCRService, SUPPORTED, load_image, write_text

VERSION = '1.0.0'
COLORS = {
    'light': dict(bg='#F6F7F9', surface='#FFFFFF', side='#F0F2F5', ink='#20262F',
                  muted='#7A8390', border='#E2E6EB', accent='#217965', soft='#E6F2ED', hover='#E9EDF1'),
    'dark': dict(bg='#15191E', surface='#1D232B', side='#191E25', ink='#E8EDF2',
                 muted='#929EAC', border='#303A46', accent='#70CCAB', soft='#243F37', hover='#29323D')}

def png_bytes(image):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data)

def app_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor('#217965'))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 17, 17)
    p.setPen(QPen(QColor('white'), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, y, dx, dy in [(17, 24, 0, -7), (17, 17, 8, 0), (47, 24, 0, -7),
                          (47, 17, -8, 0), (17, 40, 0, 7), (17, 47, 8, 0),
                          (47, 40, 0, 7), (47, 47, -8, 0), (25, 29, 14, 0), (25, 36, 10, 0)]:
        p.drawLine(x, y, x+dx, y+dy)
    p.end()
    return QIcon(pix)

def label(text, name=''):
    w = QLabel(text)
    if name: w.setObjectName(name)
    return w

def button(text, callback, name='', tip=''):
    w = QPushButton(text)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.clicked.connect(callback)
    w.setMinimumHeight(38)
    if name: w.setObjectName(name)
    if tip: w.setToolTip(tip)
    return w

class ImageView(QWidget):
    clicked = Signal()
    def __init__(self):
        super().__init__()
        self.pixmap = QPixmap()
        self.colors = COLORS['light']
        self.setMinimumSize(240, 220)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('点击选择图片，也可以拖入图片或按 Ctrl+V 粘贴')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.pixmap.isNull():
            r = self.rect().adjusted(20, 20, -20, -20)
            p.setPen(QPen(QColor(self.colors['border']), 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 14, 14)
            cx, cy = r.center().x(), r.center().y()-45
            p.setPen(QPen(QColor(self.colors['accent']), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawRoundedRect(cx-24, cy-22, 48, 44, 7, 7)
            p.drawEllipse(QPoint(cx-9, cy-6), 4, 4)
            p.drawLine(cx-20, cy+15, cx-3, cy-1)
            p.drawLine(cx-3, cy-1, cx+7, cy+9)
            p.drawLine(cx+7, cy+9, cx+14, cy+2)
            p.drawLine(cx+14, cy+2, cx+22, cy+13)
            p.setPen(QColor(self.colors['ink']))
            p.setFont(QFont('Microsoft YaHei UI', 12))
            p.drawText(QRect(r.x(), cy+43, r.width(), 30), Qt.AlignmentFlag.AlignCenter, '把图片放在这里')
            p.setPen(QColor(self.colors['muted']))
            p.setFont(QFont('Microsoft YaHei UI', 9))
            p.drawText(QRect(r.x(), cy+79, r.width(), 24), Qt.AlignmentFlag.AlignCenter, '拖入图片 · 点击打开 · Ctrl+V 粘贴')
            p.drawText(QRect(r.x(), cy+109, r.width(), 24), Qt.AlignmentFlag.AlignCenter, 'PNG / JPG / WEBP / BMP / TIFF')
        else:
            target = self.pixmap.size().scaled(self.size()-QSize(32,32), Qt.AspectRatioMode.KeepAspectRatio)
            rect = QRect(QPoint((self.width()-target.width())//2, (self.height()-target.height())//2), target)
            p.drawPixmap(rect, self.pixmap)
        p.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.clicked.emit()

class Worker(QThread):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    def __init__(self, service, job_id, source):
        super().__init__()
        self.service, self.job_id, self.source = service, job_id, source
    def run(self):
        try: self.succeeded.emit(self.job_id, self.service.recognize(self.source))
        except Exception as exc: self.failed.emit(self.job_id, str(exc))

class CaptureOverlay(QWidget):
    selected = Signal(object)
    cancelled = Signal()
    def __init__(self, screen, pixmap):
        super().__init__()
        self.background = pixmap
        self.start_point = self.end_point = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.background)
        p.fillRect(self.rect(), QColor(10, 18, 25, 120))
        if self.start_point is not None:
            r = QRect(self.start_point, self.end_point).normalized().intersected(self.rect())
            dpr = self.background.devicePixelRatio()
            src = QRect(round(r.x()*dpr),round(r.y()*dpr),round(r.width()*dpr),round(r.height()*dpr))
            p.drawPixmap(r, self.background, src)
            p.setPen(QPen(QColor('#78E1BA'), 2))
            p.drawRect(r)
        p.fillRect(QRect(20, 20, 350, 42), QColor('#1D232B'))
        p.setPen(QColor('white'))
        p.drawText(QRect(34, 20, 330, 42), Qt.AlignmentFlag.AlignVCenter, '拖动选择识别区域    ·    Esc / 右键取消')
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton: self.cancelled.emit(); return
        self.start_point = self.end_point = event.position().toPoint()
        self.update()
    def mouseMoveEvent(self, event):
        if self.start_point is not None: self.end_point = event.position().toPoint(); self.update()
    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.start_point is None: return
        r = QRect(self.start_point, event.position().toPoint()).normalized().intersected(self.rect())
        if r.width() < 6 or r.height() < 6: self.cancelled.emit(); return
        dpr = self.background.devicePixelRatio()
        crop = self.background.copy(round(r.x()*dpr), round(r.y()*dpr), round(r.width()*dpr), round(r.height()*dpr))
        crop.setDevicePixelRatio(1)
        self.selected.emit(crop.toImage())
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape: self.cancelled.emit()

class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback): super().__init__(); self.callback = callback
    def nativeEventFilter(self, event_type, message):
        if os.name == 'nt':
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == 0x531:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0

class MainWindow(QMainWindow):
    def __init__(self, register_hotkey=True):
        super().__init__()
        self.setWindowTitle('拾字 · 离线文字识别')
        self.setWindowIcon(app_icon())
        self.resize(1180, 780)
        self.setMinimumSize(960, 640)
        self.service = OCRService()
        self.records = {}
        self.jobs = deque()
        self.counter = 0
        self.worker = None
        self.active_id = None
        self.overlays = []
        self.capture_pending = False
        self.quitting = False
        self.hotkey_registered = False
        self.theme = 'light'
        self.setAcceptDrops(True)
        self.build_ui()
        self.apply_theme()
        self.setup_tray()
        self.shortcuts = []
        for keys, fn in [('Ctrl+O',self.open_files), ('Ctrl+V',self.paste),
                         ('Ctrl+Shift+C',self.copy_text), ('Ctrl+S',self.export_text)]:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(fn)
            self.shortcuts.append(shortcut)
        if os.name == 'nt' and register_hotkey:
            user32 = ctypes.windll.user32
            user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self.hotkey_registered = bool(user32.RegisterHotKey(int(self.winId()), 0x531, 0x4000 | 0x2 | 0x4, 0x53))
            self.native_filter = HotkeyFilter(self.capture)
            QApplication.instance().installNativeEventFilter(self.native_filter)
            if not self.hotkey_registered:
                self.shortcut_hint.setText('截图快捷键已被占用，请使用上方按钮')
                QTimer.singleShot(800, lambda:self.notify('Ctrl+Alt+S 已被其他程序占用，仍可点击「截图识别」。'))

    def build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        layout = QHBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        side = QFrame(); side.setObjectName('sidebar'); side.setFixedWidth(208)
        sl = QVBoxLayout(side); sl.setContentsMargins(20,26,20,20); sl.setSpacing(16)
        brand = QHBoxLayout(); icon = QLabel(); icon.setPixmap(app_icon().pixmap(38,38))
        brand.addWidget(icon); bl = QVBoxLayout(); bl.setSpacing(1)
        bl.addWidget(label('拾字','brand')); bl.addWidget(label('SHIZI  /  OCR','eyebrow'))
        brand.addLayout(bl); brand.addStretch(); sl.addLayout(brand)
        sl.addSpacing(16)
        sl.addWidget(button('＋  新的识别', self.new_session, 'navActive', '清空工作区，已有结果保留在本次记录中'))
        hr = QHBoxLayout(); hr.addWidget(label('本次记录','muted')); hr.addStretch()
        hr.addWidget(button('清空',self.clear_history,'tiny','清空本次记录和工作区'))
        sl.addLayout(hr)
        self.history = QListWidget(); self.history.setObjectName('history')
        self.history.setSpacing(4); self.history.currentRowChanged.connect(self.select_record)
        sl.addWidget(self.history,1)
        sl.addWidget(label('图片与文字仅在本机处理','small'))
        sl.addWidget(label('退出后不保留识别记录','small'))
        theme_row = QHBoxLayout(); theme_row.addWidget(label('外观','muted'))
        self.theme_combo = QComboBox(); self.theme_combo.addItems(['浅色','深色']); self.theme_combo.currentIndexChanged.connect(self.change_theme)
        theme_row.addWidget(self.theme_combo,1); sl.addLayout(theme_row)
        sl.addWidget(label('拾字  1.0  ·  本地离线','small'))
        layout.addWidget(side)
        body = QWidget(); main = QVBoxLayout(body); main.setContentsMargins(30,27,30,20); main.setSpacing(20)
        title_row = QHBoxLayout(); title_row.addWidget(label('工作台','eyebrow')); title_row.addStretch()
        title_row.addWidget(label('●  离线识别','badge')); main.addLayout(title_row)
        headings = QVBoxLayout(); headings.setSpacing(8)
        headings.addWidget(label('图片转文字，简单一点。','title'))
        headings.addWidget(label('截一张图，或放入图片。文字即刻可用。','subtitle')); main.addLayout(headings)
        actions = QHBoxLayout(); actions.setSpacing(10)
        self.capture_button = button('截图识别',self.capture,'primary','全局快捷键 Ctrl+Alt+S，支持多显示器')
        self.capture_button.setMinimumWidth(128); actions.addWidget(self.capture_button)
        actions.addWidget(button('打开图片',self.open_files,tip='Ctrl+O · 支持一次选择多张图片'))
        actions.addWidget(button('粘贴图片',self.paste,tip='Ctrl+V'))
        actions.addStretch(); main.addLayout(actions)
        self.splitter = QSplitter(Qt.Orientation.Horizontal); self.splitter.setChildrenCollapsible(False); self.splitter.setHandleWidth(14)
        left = QFrame(); left.setObjectName('panel'); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(0)
        bar = QHBoxLayout(); bar.setContentsMargins(18,14,18,14)
        bar.addWidget(label('原图','panelTitle')); bar.addStretch(); self.image_meta=label('等待导入','muted'); bar.addWidget(self.image_meta)
        ll.addLayout(bar)
        self.preview = ImageView(); self.preview.clicked.connect(self.open_files); ll.addWidget(self.preview,1)
        self.source_label = label('支持截图、拖放和剪贴板图片','small'); self.source_label.setContentsMargins(18,8,18,16)
        ll.addWidget(self.source_label)
        right = QFrame(); right.setObjectName('panel'); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)
        bar2 = QHBoxLayout(); bar2.setContentsMargins(18,10,12,10)
        bar2.addWidget(label('识别结果','panelTitle')); bar2.addStretch()
        self.export_button=button('导出',self.export_text,'compact','保存为 UTF-8 文本 · Ctrl+S')
        self.copy_button=button('复制全文',self.copy_text,'copy','Ctrl+Shift+C')
        bar2.addWidget(self.export_button); bar2.addWidget(self.copy_button); rl.addLayout(bar2)
        self.editor = QPlainTextEdit(); self.editor.setPlaceholderText('识别出的文字会显示在这里\n\n可以直接编辑，然后复制或导出。')
        self.editor.setFrameShape(QFrame.Shape.NoFrame); self.editor.textChanged.connect(self.editor_changed)
        rl.addWidget(self.editor,1)
        foot=QHBoxLayout(); foot.setContentsMargins(18,12,18,16)
        self.count_label=label('0 字','small'); foot.addWidget(self.count_label); foot.addStretch()
        self.auto_copy=QCheckBox('识别后自动复制'); foot.addWidget(self.auto_copy); rl.addLayout(foot)
        self.splitter.addWidget(left); self.splitter.addWidget(right); self.splitter.setSizes([430,470]); main.addWidget(self.splitter,1)
        self.progress=QProgressBar(); self.progress.setRange(0,0); self.progress.setFixedHeight(3); self.progress.setTextVisible(False); self.progress.hide(); main.addWidget(self.progress)
        bottom=QHBoxLayout(); bottom.setSpacing(12)
        self.status=label('就绪','small'); self.status.setWordWrap(True); bottom.addWidget(self.status,1)
        self.shortcut_hint=label('Ctrl + Alt + S  截图','small'); bottom.addWidget(self.shortcut_hint)
        main.addLayout(bottom); layout.addWidget(body,1)
        self.editor_changed()

    def apply_theme(self):
        c=COLORS[self.theme]; self.preview.colors=c; self.preview.update()
        self.setStyleSheet(f'''
            QWidget {{color:{c['ink']};font-family:"Microsoft YaHei UI";font-size:13px;}}
            QMainWindow, QMainWindow > QWidget {{background:{c['bg']};}}
            QFrame#sidebar {{background:{c['side']};border-right:1px solid {c['border']};}}
            QLabel {{background:transparent;}}
            QLabel#brand {{font-size:21px;font-weight:700;}}
            QLabel#eyebrow {{color:{c['muted']};font-size:11px;letter-spacing:1px;}}
            QLabel#title {{font-size:25px;font-weight:600;}}
            QLabel#subtitle {{color:{c['muted']};font-size:13px;}}
            QLabel#muted {{color:{c['muted']};font-size:12px;}}
            QLabel#small {{color:{c['muted']};font-size:11px;}}
            QLabel#badge {{color:{c['accent']};background:{c['soft']};padding:6px 12px;border-radius:12px;font-size:11px;}}
            QLabel#panelTitle {{font-weight:600;}}
            QFrame#panel {{background:{c['surface']};border:1px solid {c['border']};border-radius:12px;}}
            QPushButton {{background:{c['surface']};border:1px solid {c['border']};border-radius:8px;padding:0 17px;}}
            QPushButton:hover {{background:{c['hover']};}}
            QPushButton:pressed {{background:{c['soft']};}}
            QPushButton:focus {{border:1px solid {c['accent']};}}
            QPushButton:disabled {{color:{c['muted']};}}
            QPushButton#primary {{background:{'#217965' if self.theme=='light' else '#327F68'};color:white;border:0;font-weight:600;}}
            QPushButton#primary:hover {{background:#2C9279;}}
            QPushButton#navActive {{background:{c['soft']};color:{c['accent']};border:0;text-align:left;}}
            QPushButton#tiny {{background:transparent;border:0;padding:0 2px;color:{c['muted']};font-size:11px;min-height:22px;}}
            QPushButton#compact {{background:transparent;border:0;padding:0 10px;min-height:30px;}}
            QPushButton#copy {{background:{c['soft']};color:{c['accent']};border:0;padding:0 13px;min-height:30px;}}
            QPlainTextEdit {{background:{c['surface']};color:{c['ink']};padding:16px;font-size:14px;selection-background-color:{c['soft']};selection-color:{c['ink']};}}
            QListWidget {{background:transparent;border:0;outline:0;}}
            QListWidget::item {{padding:12px 9px;border-radius:8px;color:{c['muted']};}}
            QListWidget::item:selected {{background:{c['surface']};color:{c['ink']};}}
            QListWidget::item:hover {{background:{c['hover']};}}
            QSplitter::handle {{background:{c['bg']};width:16px;}}
            QCheckBox {{font-size:11px;color:{c['muted']};spacing:6px;}}
            QComboBox {{background:{c['surface']};border:1px solid {c['border']};border-radius:6px;padding:5px 10px;}}
            QComboBox QAbstractItemView {{background:{c['surface']};selection-background-color:{c['soft']};}}
            QMenu {{background:{c['surface']};border:1px solid {c['border']};padding:6px;}}
            QMenu::item {{padding:8px 22px;}} QMenu::item:selected {{background:{c['soft']};}}
            QProgressBar {{border:0;background:{c['border']};}} QProgressBar::chunk {{background:{c['accent']};}}
            QScrollBar:vertical {{background:transparent;width:8px;}} QScrollBar::handle:vertical {{background:{c['border']};min-height:30px;border-radius:4px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
            QToolTip {{background:{c['surface']};color:{c['ink']};border:1px solid {c['border']};padding:6px;}}
        ''')

    def change_theme(self,index): self.theme='dark' if index else 'light'; self.apply_theme()

    def setup_tray(self):
        self.tray = QSystemTrayIcon(app_icon(),self)
        self.tray.setToolTip('拾字 · Ctrl+Alt+S 截图识别')
        menu=QMenu(self)
        menu.addAction('打开拾字',self.restore)
        menu.addAction('截图识别  Ctrl+Alt+S',self.capture)
        menu.addSeparator(); menu.addAction('退出',self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason:self.restore() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable(): self.tray.show()

    def notify(self,text): self.status.setText(text)
    def restore(self): self.showNormal(); self.raise_(); self.activateWindow()

    def open_files(self):
        files,_=QFileDialog.getOpenFileNames(self,'选择需要识别的图片','','图片 (*.png *.jpg *.jpeg *.jfif *.webp *.bmp *.tif *.tiff)')
        self.add_files(files)

    def add_files(self, files):
        supported=[p for p in files if Path(p).suffix.lower() in SUPPORTED]
        if not supported:
            if files:self.notify('请选择 PNG、JPG、WEBP、BMP 或 TIFF 图片。')
            return
        if len(supported)+len(self.jobs)>100:
            self.notify('一次最多排队 100 张图片，请分批导入。'); return
        for file in supported:self.enqueue(str(file),Path(file).name)

    def paste(self):
        clip=QApplication.clipboard(); mime=clip.mimeData()
        if mime and mime.hasImage():
            image=clip.image()
            if not image.isNull():self.enqueue(png_bytes(image),'剪贴板图片');return
        if mime and mime.hasUrls():self.add_files([u.toLocalFile() for u in mime.urls() if u.isLocalFile()]);return
        if self.editor.hasFocus() and clip.text():self.editor.insertPlainText(clip.text());return
        self.notify('剪贴板中没有图片。可先复制图片，或使用截图识别。')

    def dragEnterEvent(self,event):
        mime=event.mimeData()
        if mime.hasImage() or (mime.hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in SUPPORTED for u in mime.urls() if u.isLocalFile())):event.acceptProposedAction()
    def dropEvent(self,event):
        mime=event.mimeData()
        if mime.hasUrls():self.add_files([u.toLocalFile() for u in mime.urls() if u.isLocalFile()])
        elif mime.hasImage():
            image=QImage(mime.imageData())
            if not image.isNull():self.enqueue(png_bytes(image),'拖入的图片')
        event.acceptProposedAction()

    def enqueue(self, source, name):
        # Limit in-memory history, including queued entries; never silently discard edits.
        if len(self.records)>=100:self.notify('本次记录已达 100 条，请导出需要的结果后清空记录。');return
        self.counter+=1; key=self.counter
        self.records[key]=dict(source=source,name=name,text='',result=None,error='',state='等待中')
        item=QListWidgetItem(f'{name[:17]}\n等待识别');item.setData(Qt.ItemDataRole.UserRole,key);item.setToolTip(name)
        self.history.addItem(item);self.jobs.append(key)
        self.history.setCurrentRow(self.history.count()-1)
        self.start_next()

    def start_next(self):
        if self.worker is not None or not self.jobs:return
        key=self.jobs.popleft();record=self.records[key];record['state']='识别中'
        self.update_item(key,'识别中'); self.progress.show()
        self.notify('正在本机识别…首次加载引擎需要几秒。' if self.service.engine is None else f'正在识别 · {record["name"]}')
        self.worker=Worker(self.service,key,record['source'])
        self.worker.succeeded.connect(self.recognized); self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_finished); self.worker.start()

    def worker_finished(self):
        self.worker.deleteLater();self.worker=None
        if self.jobs:QTimer.singleShot(0,self.start_next)
        else:self.progress.hide()

    def update_item(self,key,detail):
        for i in range(self.history.count()):
            item=self.history.item(i)
            if item.data(Qt.ItemDataRole.UserRole)==key:item.setText(f'{self.records[key]["name"][:17]}\n{detail}');break

    def recognized(self,key,result):
        if key not in self.records:return
        r=self.records[key];r.update(text=result.text,result=result,state='完成')
        self.update_item(key,f'{len(result.text)} 字  ·  {result.seconds:.1f}s')
        if self.active_id==key:self.show_record(key)
        if result.text:
            self.notify(f'识别完成 · {result.lines} 行 · {result.seconds:.1f} 秒'+(f' · 剩余 {len(self.jobs)} 张' if self.jobs else ''))
            if self.auto_copy.isChecked():QApplication.clipboard().setText(result.text);self.notify('识别完成，已自动复制文字。')
        else:self.notify('未发现可识别文字，请换用更清晰的图片或缩小截图区域。')

    def failed(self,key,error):
        self.records[key].update(error=error,state='失败');self.update_item(key,'识别失败')
        if self.active_id==key:self.show_record(key)
        self.notify('识别失败：'+error[:180])

    def select_record(self,row):
        if row>=0:self.show_record(self.history.item(row).data(Qt.ItemDataRole.UserRole))

    def show_record(self,key):
        self.active_id=key;r=self.records[key]
        self.editor.blockSignals(True);self.editor.setPlainText(r['text']);self.editor.blockSignals(False)
        self.editor.setReadOnly(r['state'] in ('等待中','识别中'))
        self.editor.setPlaceholderText('正在识别，请稍候…' if r['state'] in ('等待中','识别中') else ('识别失败，请检查图片后重新导入。' if r['error'] else '这张图片中没有发现文字。'))
        try:
            image=load_image(r['source']);image.thumbnail((1600,1600))
            out=BytesIO();image.save(out,format='PNG');self.preview.pixmap=QPixmap();self.preview.pixmap.loadFromData(out.getvalue())
            result=r['result'];self.image_meta.setText(f'{result.width} × {result.height}' if result else f'{image.width} × {image.height}')
        except Exception:self.preview.pixmap=QPixmap();self.image_meta.setText('无法预览')
        self.preview.update();self.source_label.setText(r['name'][:48]);self.source_label.setToolTip(r['name'])
        self.editor_changed()

    def editor_changed(self):
        text=self.editor.toPlainText();self.count_label.setText(f'{len(text)} 字')
        self.copy_button.setEnabled(bool(text));self.export_button.setEnabled(bool(text))
        if self.active_id in self.records:self.records[self.active_id]['text']=text

    def copy_text(self):
        if self.editor.toPlainText():QApplication.clipboard().setText(self.editor.toPlainText());self.notify('已复制全文。')

    def export_text(self):
        if not self.editor.toPlainText():return
        path,_=QFileDialog.getSaveFileName(self,'导出识别结果',f'拾字_{datetime.now():%Y%m%d_%H%M%S}.txt','文本文档 (*.txt)')
        if path:
            try:write_text(path,self.editor.toPlainText());self.notify('已导出 · '+Path(path).name)
            except OSError as exc:self.notify('保存失败：'+str(exc))

    def new_session(self):
        self.history.setCurrentRow(-1);self.active_id=None;self.editor.setReadOnly(False)
        self.editor.clear();self.editor.setPlaceholderText('识别出的文字会显示在这里\n\n可以直接编辑，然后复制或导出。')
        self.preview.pixmap=QPixmap();self.preview.update();self.image_meta.setText('等待导入');self.source_label.setText('支持截图、拖放和剪贴板图片');self.notify('就绪')

    def clear_history(self):
        if self.worker is not None or self.jobs:self.notify('识别进行中，请等待完成后清空记录。');return
        self.active_id=None;self.records.clear();self.history.clear();self.new_session();self.notify('本次记录已清空。')

    def capture(self):
        if self.capture_pending or self.overlays:return
        self.capture_pending=True;self.was_visible=self.isVisible();self.hide()
        QTimer.singleShot(250,self.begin_capture)

    def begin_capture(self):
        try:
            # Freeze every monitor before showing any overlay. Each monitor retains its own DPI.
            screens=[(s,s.grabWindow(0)) for s in QApplication.screens()]
            if not screens or any(p.isNull() for _,p in screens):raise RuntimeError('无法读取屏幕，请检查屏幕捕获权限。')
            for screen,pix in screens:
                overlay=CaptureOverlay(screen,pix);overlay.selected.connect(self.finish_capture);overlay.cancelled.connect(self.cancel_capture)
                self.overlays.append(overlay)
            for overlay in self.overlays:overlay.show();overlay.raise_()
            cursor_screen=QApplication.screenAt(self.cursor().pos())
            index=QApplication.screens().index(cursor_screen) if cursor_screen in QApplication.screens() else 0
            self.overlays[index].activateWindow();self.overlays[index].setFocus()
        except Exception as exc:self.cancel_capture();self.restore();self.notify(str(exc))
        finally:self.capture_pending=False

    def close_overlays(self):
        for overlay in self.overlays:overlay.close()
        self.overlays=[]
    def finish_capture(self,image):
        self.close_overlays();self.restore();self.enqueue(png_bytes(image),'截图 '+datetime.now().strftime('%H:%M:%S'))
    def cancel_capture(self):
        self.close_overlays()
        if getattr(self,'was_visible',True):self.restore()

    def quit_app(self):
        if self.worker is not None or self.jobs:self.restore();self.notify('正在识别，请等待任务完成后退出。');return
        self.quitting=True;self.close()

    def closeEvent(self,event):
        if self.worker is not None or self.jobs:event.ignore();self.notify('正在识别，请等待任务完成后关闭。');return
        if self.hotkey_registered:ctypes.windll.user32.UnregisterHotKey(int(self.winId()),0x531)
        self.close_overlays();self.tray.hide();event.accept();QApplication.instance().quit()

def main():
    app=QApplication(sys.argv);app.setApplicationName('拾字');app.setOrganizationName('Shizi')
    app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10))
    lock=QLockFile(QDir.tempPath()+'/shizi-ocr-v1.lock');lock.setStaleLockTime(0)
    if not lock.tryLock(100):return 0
    window=MainWindow();window.show()
    if '--smoke-test' in sys.argv:
        from PySide6.QtTest import QTest
        smoke_elapsed = [0]
        if '--verify-image' in sys.argv:
            window.enqueue(sys.argv[sys.argv.index('--verify-image')+1], '打包程序离线核验')
        def smoke():
            if window.worker is not None or window.jobs:
                smoke_elapsed[0] += 1
                if smoke_elapsed[0] < 120:
                    QTimer.singleShot(500,smoke)
                    return
            report=Path(sys.argv[sys.argv.index('--smoke-test')+1]);report.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(report.with_suffix('.png')))
            report.write_text(json.dumps(dict(title=window.windowTitle(),visible=window.isVisible(),width=window.width(),height=window.height(),hotkey=window.hotkey_registered,text=window.editor.toPlainText(),records=[dict(name=r['name'],state=r['state'],error=r['error']) for r in window.records.values()]),ensure_ascii=False,indent=2),encoding='utf-8')
            window.quit_app()
        QTimer.singleShot(1200,smoke)
    return app.exec()

if __name__=='__main__':sys.exit(main())
