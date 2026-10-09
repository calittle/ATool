"""Real embedded chip-editor parity checks. Temporary settings; no Comms requests."""
import html
import json
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QPoint, Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem
from PySide6.QtTest import QTest
from atool_qt.window import WorkspaceWindow
from atool_qt.user_settings import UserSettings
from atool_qt.session import demo_session

app=QApplication([])
temporary=tempfile.TemporaryDirectory()
root=Path(temporary.name)
window=WorkspaceWindow(QSettings(str(root/'qt.ini'),QSettings.Format.IniFormat))
settings=UserSettings(root/'user.json');settings.payload['application']['confirm_on_quit']=False
window.comms.settings=settings
window.set_session(demo_session())
panel=window.content
window.show();window.show_panel('content');panel.tabs.setCurrentIndex(0)
rich=panel.rich

def wait(predicate):
    deadline=time.monotonic()+15
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert predicate(),'Timed out waiting for embedded editor'

def js(code):
    output=[];rich.page().runJavaScript(code,output.append)
    wait(lambda:bool(output));return output[0]

def json_js(expression):
    return json.loads(js('JSON.stringify('+expression+')'))

def load(raw,encoded=False):
    source='<p>'+ (html.escape(raw) if encoded else raw) +'</p>'
    panel.source.setPlainText(source)
    wait(lambda:js('snapshot()')==source)
    assert js("editor.querySelectorAll('.chip').length")==1
    panel.baseline=panel.snapshot()
    return source

def click_save():
    js("document.getElementById('chip-save').click()")
    app.processEvents()

def open_chip():
    js("editChip(editor.querySelector('.chip'))")

wait(lambda:rich.ready)
# Original structural table controls, exercised through their actual buttons.
def table_load(source):
    panel.source.setPlainText(source)
    wait(lambda:js('snapshot()')==source)
    panel.baseline=panel.snapshot()

def select(selector):
    js("document.querySelector('.tools').open=false")
    app.processEvents()
    center=json_js('(()=>{const r=editor.querySelector('+json.dumps(selector)+').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    QTest.mouseClick(rich.focusProxy() or rich,Qt.MouseButton.LeftButton,pos=QPoint(round(center[0]),round(center[1])))
    wait(lambda:js('activeCell===editor.querySelector('+json.dumps(selector)+')'))

def click(command):
    js("document.querySelector('.tools').open=true;positionTableTools()")
    app.processEvents()
    center=json_js('(()=>{const r=document.querySelector('+json.dumps('[data-command="'+command+'"]')+').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()')
    QTest.mouseClick(rich.focusProxy() or rich,Qt.MouseButton.LeftButton,pos=QPoint(round(center[0]),round(center[1])))
    app.processEvents()

def rows():
    return json_js("[...editor.querySelector('table').rows].map(row=>[...row.cells].map(cell=>cell.textContent))")

simple='<table data-keep="table"><tr><td data-keep="a">A</td><td>B</td></tr><tr><td>C</td><td>D</td></tr></table>'
for command, expected in [('addRow(true)', [['', ''], ['A', 'B'], ['C', 'D']]),
                          ('addRow(false)', [['A', 'B'], ['', ''], ['C', 'D']]),
                          ('addColumn(true)', [['', 'A', 'B'], ['', 'C', 'D']]),
                          ('addColumn(false)', [['A', '', 'B'], ['C', '', 'D']]),
                          ('splitCell(false)', [['A', '', 'B'], ['C', '', 'D']]),
                          ('splitCell(true)', [['A', 'B'], ['', ''], ['C', 'D']])]:
    table_load(simple);select('td');click(command)
    assert rows()==expected,(command,rows())
    wait(lambda:panel.dirty)
    assert js("editor.querySelector('table').dataset.keep")=='table'
    assert js("editor.querySelector('[data-keep=a]').textContent")=='A'
    js("cmd('undo')");wait(lambda:not panel.dirty)
    assert js('snapshot()')==simple
    js("cmd('redo')");wait(lambda:panel.dirty)
    assert rows()==expected

for command, selected, expected, span in [
    ('mergeRight()', 'tr:first-child td:first-child', [['AB'], ['C', 'D']], 'colSpan'),
    ('mergeLeft()', 'tr:first-child td:last-child', [['AB'], ['C', 'D']], 'colSpan'),
    ('mergeDown()', 'tr:first-child td:first-child', [['AC', 'B'], ['D']], 'rowSpan'),
    ('mergeUp()', 'tr:last-child td:first-child', [['AC', 'B'], ['D']], 'rowSpan')]:
    table_load(simple);select(selected);click(command)
    assert rows()==expected,(command,rows())
    assert js('editor.querySelector("td").'+span)==2
    assert '<br>' in js('editor.querySelector("td").innerHTML')
    assert js("editor.querySelector('td').dataset.keep")=='a'
    wait(lambda:panel.dirty)
    js("cmd('undo')");wait(lambda:not panel.dirty);assert js('snapshot()')==simple

spans='<table><tr><td rowspan="2" data-keep="a">A</td><td colspan="2">B</td></tr><tr><td>C</td><td>D</td></tr><tr><td>E</td><td>F</td><td>G</td></tr></table>'
table_load(spans);select('td');click('addRow(false)')
assert rows()==[['A', 'B'], ['', ''], ['C', 'D'], ['E', 'F', 'G']]
assert js('editor.querySelector("td").rowSpan')==3
# A vertical merge must find the next row beyond the entire rowspan.
table_load(spans);select('td');click('mergeDown()')
assert rows()==[['AE', 'B'], ['C', 'D'], ['F', 'G']]
assert js('editor.querySelector("td").rowSpan')==3
# Merge up finds the same spanning cell rather than a same-index neighbor.
table_load(spans);select('tr:last-child td:first-child');click('mergeUp()')
assert rows()==[['AE', 'B'], ['C', 'D'], ['F', 'G']]
assert js('editor.querySelector("td").rowSpan')==3
# Column insertion accounts for the cells hidden behind rowspans.
table_load(spans);select('td');click('addColumn(false)')
assert rows()==[['A', '', 'B'], ['', 'C', 'D'], ['E', '', 'F', 'G']]
# A cell split preserves the remaining colspan/rowspan rectangle and metadata.
table_load(spans);select('tr:first-child td:last-child');click('splitCell(false)')
assert rows()==[['A', 'B', ''], ['C', 'D'], ['E', 'F', 'G']]
assert js('editor.querySelector("td").rowSpan')==2
both='<table><tr><td rowspan="2" colspan="2" data-keep="both">Big</td><td>R</td></tr><tr><td>S</td></tr><tr><td>A</td><td>B</td><td>C</td></tr></table>'
table_load(both);select('td');click('splitCell(true)')
assert rows()==[['Big', 'R'], ['', 'S'], ['A', 'B', 'C']]
assert js('editor.querySelector("td").colSpan')==2
assert js('editor.querySelector("tr:nth-child(2) td").colSpan')==2
assert js('editor.querySelector("td").dataset.keep')=='both'
table_load(both);select('td');click('splitCell(false)')
assert rows()==[['Big', '', 'R'], ['S'], ['A', 'B', 'C']]
assert js('editor.querySelector("tr:first-child td:nth-child(2)").rowSpan')==2
# Incompatible and boundary merges are no-ops with no undo or dirty state.
for source, selector, command in [(simple, 'td', 'mergeLeft()'), (simple, 'td', 'mergeUp()'),
                                 (simple, 'tr:last-child td:last-child', 'mergeRight()'),
                                 (simple, 'tr:last-child td:last-child', 'mergeDown()'),
                                 (spans, 'tr:first-child td:last-child', 'mergeDown()')]:
    table_load(source);select(selector);click(command)
    assert js('snapshot()')==source,(selector,command,js('snapshot()'))
    assert not panel.dirty
    assert js('undoStack.length')==0
js("document.querySelector('.tools').open=true;positionTableTools()")
assert js("(()=>{const r=document.querySelector('.tools > div').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight})()"), 'Table tools must fit in a narrow editor'
rich.grab().save('/private/tmp/atool-table-controls.png')
panel.baseline=panel.snapshot();window.close();temporary.cleanup()
print('Embedded table structural controls passed')
