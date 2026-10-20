"""Real-engine and Qt interaction checks. Run with the project venv."""
from pathlib import Path
import sys, time, json, tempfile, socket
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage, QPixmap
from main import MainWindow, CaptureOverlay
from core import OCRService, load_image, write_text

root=Path(__file__).resolve().parents[1]
work=root/'work';work.mkdir(exist_ok=True)
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',42)
image=Image.new('RGB',(1050,350),'white');d=ImageDraw.Draw(image)
for y,text in [(35,'拾字 · 让文字触手可及'),(110,'离线识别，简单高效。'),(185,'Hello OCR 12345'),(260,'中文与 English 都可以识别')]:d.text((40,y),text,font=font,fill='#20262F')
sample=work/'中英文识别样张.png';image.save(sample)

# Disable Python networking for the actual inference test.
original_socket=socket.socket
def forbidden(*a,**kw):raise AssertionError('OCR must not access the network')
socket.socket=forbidden
result=OCRService().recognize(sample)
socket.socket=original_socket
assert '12345' in result.text and '离线识别' in result.text and 'English' in result.text,result.text
assert result.lines >= 4
blank=work/'blank.png';Image.new('RGB',(300,200),'white').save(blank)
service=OCRService();assert service.recognize(blank).text==''
try:load_image(b'corrupt');raise AssertionError('Invalid image accepted')
except (OSError,ValueError):pass
rgba=work/'transparent.png';Image.new('RGBA',(20,20),(0,0,0,0)).save(rgba)
assert load_image(rgba).getpixel((0,0))==(255,255,255)
write_text(work/'导出核验.txt',result.text);assert (work/'导出核验.txt').read_text(encoding='utf-8-sig')==result.text

app=QApplication([]);app.setStyle('Fusion')
window=MainWindow(register_hotkey=False);window.show();QTest.qWait(300)
window.grab().save(str(work/'界面_浅色.png'))
window.theme_combo.setCurrentIndex(1);QTest.qWait(200);window.grab().save(str(work/'界面_深色.png'));window.theme_combo.setCurrentIndex(0)
window.enqueue(str(sample),sample.name)
deadline=time.monotonic()+90
while window.worker is not None or window.jobs:
    QTest.qWait(50)
    if time.monotonic()>deadline:raise AssertionError('OCR queue timeout')
assert '12345' in window.editor.toPlainText()
window.editor.appendPlainText('手动修订');window.copy_button.click()
assert '手动修订' in app.clipboard().text()
window.grab().save(str(work/'界面_识别完成.png'))
window.new_session();assert not window.editor.toPlainText()
window.history.setCurrentRow(0);assert '手动修订' in window.editor.toPlainText()
app.clipboard().setImage(QImage(str(sample)));window.paste()
while window.worker is not None or window.jobs:QTest.qWait(50)
assert len(window.records)==2
# Unicode import, no-text image, invalid-file recovery, and continued queue processing.
window.enqueue(b'corrupt','损坏图片');window.enqueue(str(blank),'空白图片')
while window.worker is not None or window.jobs:QTest.qWait(50)
assert window.records[3]['state']=='失败' and window.records[4]['state']=='完成'

# Exercise selection against a synthetic frozen screen, avoiding unrelated desktop contents.
frozen=QPixmap.fromImage(QImage(str(sample)));overlay=CaptureOverlay(app.primaryScreen(),frozen)
overlay.resize(1050,350);overlay.show();QTest.qWait(100);captured=[]
overlay.selected.connect(captured.append)
QTest.mousePress(overlay,Qt.MouseButton.LeftButton,pos=QPoint(20,20))
QTest.mouseMove(overlay,QPoint(500,220));QTest.mouseRelease(overlay,Qt.MouseButton.LeftButton,pos=QPoint(500,220))
assert captured and 475<=captured[0].width()<=485
overlay.close()
window.clear_history();assert not window.records and not window.editor.toPlainText()
window.close();app.processEvents()
report=dict(passed=True,recognized_text=result.text,lines=result.lines,confidence=result.confidence,seconds=result.seconds,
            checks=['real offline Chinese/English OCR','blank input','corrupt input','Unicode paths','transparent image',
                    'UTF-8 export','light/dark render','worker queue recovery','edit/copy','session history',
                    'clipboard image','region selection','clear history'])
(work/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
