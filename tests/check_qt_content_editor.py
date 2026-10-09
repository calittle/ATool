"""Standalone WebEngine verification; uses temporary settings and no Comms calls.

Run with QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu
.venv/bin/python tests/check_qt_content_editor.py. macOS WebEngine requires native
process access unavailable in the restricted shell sandbox.
"""
import os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from atool_qt.window import WorkspaceWindow
from atool_qt.user_settings import UserSettings
from atool_qt.session import demo_session
app=QApplication([])
temp_directory=tempfile.TemporaryDirectory()
root=Path(temp_directory.name)
window=WorkspaceWindow(QSettings(str(root/'qt.ini'), QSettings.IniFormat))
settings=UserSettings(root/'user.json')
settings.payload['application']['confirm_on_quit']=False
window.comms.settings=settings
window.set_session(demo_session())
panel=window.content
html='<p class="unknown" data-preserve="yes">Hello <comms-data>$Data{"Id":"Account"}</comms-data></p><table><tr><td>Cell</td><td>Other</td></tr></table>'
panel.source.setPlainText(html)
panel.baseline=panel.snapshot()
window.show()
app.processEvents()
window.show_panel('content')
panel.tabs.setCurrentIndex(0)
rich=panel.rich
def wait(predicate):
    deadline=time.monotonic()+15
    while not predicate() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), 'Timed out waiting for embedded HTML editor'
def js(code):
    output=[]
    rich.page().runJavaScript(code, output.append)
    wait(lambda:bool(output))
    return output[0]
wait(lambda:rich.ready)
assert js('snapshot()')==html
assert not panel.dirty
assert js("editor.querySelectorAll('.chip').length")==1
js("selectCell(editor.querySelector('td'))")
assert js('snapshot()')==html, 'Cell selection must not alter source'
js("document.querySelector('[data-command=\"insertTable()\"]').click()")
wait(lambda:panel.dirty)
saved=js('snapshot()')
assert '<comms-data>$Data{"Id":"Account"}</comms-data>' in saved
assert 'data-preserve="yes"' in saved
assert 'class="active"' not in saved
assert js("editor.querySelectorAll('table').length")==2
js("cmd('undo')")
wait(lambda:not panel.dirty)
assert js('snapshot()')==html
js("cmd('redo')")
wait(lambda:panel.dirty)
assert js("editor.querySelectorAll('table').length")==2
js('insertMarkup(\'<comms-data>$Data{"Id":"Inserted"}</comms-data>\')')
wait(lambda:'Inserted' in panel.source.toPlainText())
# Changing source invalidates delayed editor events.
panel.source.setPlainText('<p>Fresh source</p>')
rich.bridge.changed(rich.generation-1,'old stale edit')
assert panel.source.toPlainText()=='<p>Fresh source</p>'
assert js('snapshot()')=='<p>Fresh source</p>'
window.grab().save('/private/tmp/atool-content-rich.png')
panel.baseline=panel.snapshot()
window.close()
temp_directory.cleanup()
print('Embedded editor checks passed')
