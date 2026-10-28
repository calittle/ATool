"""Real WebEngine context targeting, markup preservation, tables, and undo."""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from atool_qt.session import demo_session
from atool_qt.user_settings import UserSettings
from atool_qt.window import WorkspaceWindow

app = QApplication([])
temporary = tempfile.TemporaryDirectory()
root = Path(temporary.name)
window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.Format.IniFormat))
window.comms.settings = UserSettings(root / 'user.json')
window.comms.settings.payload['application']['confirm_on_quit'] = False
window.set_session(demo_session())
window.show()
window.show_panel('content')
panel = window.content
panel.tabs.setCurrentIndex(0)
rich = panel.rich


def wait(predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), 'Timed out waiting for embedded editor'


def js(code):
    output = []
    rich.page().runJavaScript(code, output.append)
    wait(lambda: bool(output))
    return output[0]


def load(html):
    panel.source.setPlainText(html)
    wait(lambda: js('snapshot()') == html)
    panel.baseline = panel.snapshot()


def context(selector):
    previous = getattr(rich, '_context_menu', None)
    js('(()=>{const node=editor.querySelector(' + json.dumps(selector) + ');const rect=node.getBoundingClientRect();node.dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,cancelable:true,clientX:rect.left+4,clientY:rect.top+4}));})()')
    wait(lambda: getattr(rich, '_context_menu', None) is not None and rich._context_menu is not previous)
    return rich._context_menu


def trigger(menu, title):
    action = next(action for action in menu.actions() if action.text() == title)
    assert action.isEnabled(), title
    action.trigger()
    menu.close()
    app.processEvents()


wait(lambda: rich.ready)
try:
    raw = '<comms-data>$Data{"Id":"Amount","Extra":{"keep":true}}</comms-data>'
    original = '<p>Hello ' + raw + '</p>'
    load(original)
    menu = context('.chip')
    assert js('snapshot()') == original and not panel.dirty
    trigger(menu, 'Copy Field Markup')
    assert app.clipboard().text() == raw
    menu = context('.chip')
    trigger(menu, 'Remove Field Chip')
    wait(lambda: js('editor.querySelectorAll(".chip").length') == 0)
    js('cmd("undo")')
    wait(lambda: js('snapshot()') == original)
    assert not panel.dirty
    menu = context('.chip')
    trigger(menu, 'Edit Field…')
    wait(lambda: js('document.querySelector("#chip-field")!==null'))
    js('document.querySelector("#chip-field").value="Changed";document.querySelector("#chip-save").click()')
    wait(lambda: 'Changed' in panel.source.toPlainText())
    assert '"keep":true' in panel.source.toPlainText()

    # A stale menu cannot act on the next loaded document.
    menu = context('.chip')
    load('<p>Replacement</p>')
    trigger(menu, 'Remove Field Chip')
    assert js('snapshot()') == '<p>Replacement</p>'

    load('<table><tbody><tr><td>A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></tbody></table>')
    menu = context('td')
    table = next(action.menu() for action in menu.actions() if action.text() == 'Table')
    assert not next(action for action in table.actions() if action.text() == 'Merge Left').isEnabled()
    assert next(action for action in table.actions() if action.text() == 'Merge Right').isEnabled()
    trigger(table, 'Insert Row Above')
    menu.close()
    wait(lambda: js('editor.querySelector("table").rows.length') == 3)
    js('cmd("undo")')
    wait(lambda: js('editor.querySelector("table").rows.length') == 2)

    # Keyboard invocation keeps the current text range and exposes link actions.
    load('<p><a href="https://example.com/test">Selected link</a></p>')
    previous = getattr(rich, '_context_menu', None)
    js('(()=>{const range=document.createRange();range.selectNodeContents(editor.querySelector("a"));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);editor.focus();editor.dispatchEvent(new KeyboardEvent("keydown",{bubbles:true,cancelable:true,key:"F10",shiftKey:true}));})()')
    wait(lambda: getattr(rich, '_context_menu', None) is not None and rich._context_menu is not previous)
    menu = rich._context_menu
    trigger(menu, 'Copy Link Address')
    assert app.clipboard().text() == 'https://example.com/test'
    assert js('window.getSelection().toString()') == 'Selected link'
    print('Embedded context menus: chips, stale targets, tables, keyboard selection, and undo passed.')
finally:
    panel.baseline = panel.snapshot()
    window.close()
    temporary.cleanup()
