from pathlib import Path
import sys, ctypes, json
from ctypes import wintypes
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from main import MainWindow
app=QApplication([]);window=MainWindow();window.show();QTest.qWait(200)
assert window.hotkey_registered,'Global shortcut registration failed'
received=[];window.native_filter.callback=lambda:received.append(True)
user32=ctypes.windll.user32
user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
assert user32.PostMessageW(int(window.winId()),0x0312,0x531,0)
QTest.qWait(300)
assert received,'Native global shortcut event was not delivered'
window.close();app.processEvents()
report=dict(passed=True,registration=True,native_event_dispatch=True)
(Path(__file__).resolve().parents[1]/'work'/'hotkey_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(report)
