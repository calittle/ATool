"""Real embedded-editor formatting controls; temporary settings, no Comms calls."""
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
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    window = WorkspaceWindow(QSettings(str(root / 'qt.ini'), QSettings.IniFormat))
    settings = UserSettings(root / 'user.json')
    settings.payload['application']['confirm_on_quit'] = False
    window.comms.settings = settings
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
        assert predicate(), 'Embedded editor did not respond'

    def js(code):
        output = []
        rich.page().runJavaScript(code, output.append)
        wait(lambda: bool(output))
        return output[0]

    def click(command):
        js('document.querySelector(' + json.dumps('[data-command="' + command + '"]') + ').click()')

    raw = '<p class="preserved" data-unknown="keep"><span style="font-size:18pt">Alpha beta</span></p>'

    def load():
        panel.source.setPlainText(raw)
        wait(lambda: js('snapshot()') == raw)
        panel.baseline = panel.snapshot()
        js("(()=>{const text=editor.querySelector('span').firstChild;const r=document.createRange();r.setStart(text,0);r.setEnd(text,5);window.getSelection().removeAllRanges();window.getSelection().addRange(r)})()")

    wait(lambda: rich.ready)
    # All direct formatting buttons preserve unrelated markup and support one Undo/Redo.
    for command, selector in [('bold', 'b,strong'), ('italic', 'i,em'), ('underline', 'u'),
                              ('insertUnorderedList', 'ul'), ('insertOrderedList', 'ol')]:
        load()
        click("cmd('" + command + "')")
        wait(lambda: panel.dirty)
        assert js('!!editor.querySelector(' + json.dumps(selector) + ')'), command
        assert js("!!editor.querySelector('[data-unknown=keep]')"), command
        click("cmd('undo')")
        wait(lambda: not panel.dirty)
        assert js('snapshot()') == raw
        click("cmd('redo')")
        wait(lambda: panel.dirty)
        assert js('!!editor.querySelector(' + json.dumps(selector) + ')')

    # Cancel and empty Apply do not dirty or normalize the exact source.
    load()
    click('chooseFormat()')
    assert js("document.querySelector('#format-size').value") == ''
    assert json.loads(js("JSON.stringify([...document.querySelector('#format-size').options].map(o=>o.value))")) == ['', '10pt', '11pt', '12pt', '14pt', '16pt', '18pt', '24pt']
    js("document.querySelector('#format-link').value='https://example.invalid';document.querySelector('#format-cancel').click()")
    assert js('snapshot()') == raw
    click('chooseFormat()')
    js("document.querySelector('#format-save').click()")
    assert js('snapshot()') == raw
    assert not panel.dirty

    # A link/color change retains existing point size; size/classes affect only selected text.
    load()
    click('chooseFormat()')
    js("document.querySelector('#format-link').value='https://example.invalid';document.querySelector('#format-fore').value='#123456';document.querySelector('#format-back').value='#fedcba';document.querySelector('#format-save').click()")
    wait(lambda: panel.dirty)
    assert js("editor.querySelector('a').textContent") == 'Alpha'
    assert js("editor.querySelector('a').getAttribute('href')") == 'https://example.invalid'
    assert not js("!!editor.querySelector('font[size]')")
    assert js("editor.querySelector('span').style.fontSize") == '18pt'
    assert js("(()=>{const walker=document.createTreeWalker(editor.querySelector('a'),NodeFilter.SHOW_TEXT);return getComputedStyle(walker.nextNode().parentElement).color})()") == 'rgb(18, 52, 86)', js('snapshot()')
    assert js("[...editor.querySelectorAll('*')].some(e=>e.style.backgroundColor==='rgb(254, 220, 186)')")
    click("cmd('undo')")
    wait(lambda: not panel.dirty)
    assert js('snapshot()') == raw
    load()
    click('chooseFormat()')
    js("document.querySelector('#format-size').value='14pt';document.querySelector('#format-class').value='custom emphasis';document.querySelector('#format-save').click()")
    wait(lambda: panel.dirty)
    assert js("editor.querySelector('.custom.emphasis').textContent") == 'Alpha'
    assert js("editor.querySelector('.custom.emphasis').style.fontSize") == '14pt'
    assert js("editor.querySelector('p').textContent") == 'Alpha beta'
    click("cmd('undo')")
    wait(lambda: not panel.dirty)
    assert js('snapshot()') == raw

    # Source replacement invalidates an already captured Apply handler/range.
    load()
    click('chooseFormat()')
    js("document.querySelector('#format-size').value='24pt';window.oldApply=document.querySelector('#format-save').onclick")
    panel.source.setPlainText('<p>Replacement</p>')
    wait(lambda: js('snapshot()') == '<p>Replacement</p>')
    js('window.oldApply()')
    assert js('snapshot()') == '<p>Replacement</p>'
    panel.baseline = panel.snapshot()
    window.close()
print('Embedded formatting controls passed')
