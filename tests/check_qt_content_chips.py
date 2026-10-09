"""Real embedded chip-editor parity checks. Temporary settings; no Comms requests."""
import html
import json
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QTreeWidgetItem
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
# Data type options, format suggestions, custom properties, cancel, and undo.
raw='<comms-data>$Data'+json.dumps({'Extra':{'keep':True},'Id':'Amount','Type':'Decimal','Format':'custom'})+'</comms-data>'
source=load(raw);open_chip()
assert json_js("[...document.querySelector('#chip-type').options].map(o=>o.value)")==['','String','Decimal','Date','DateTime','Image','PDF']
assert '$#,##0.00' in json_js("[...document.querySelector('#chip-formats').options].map(o=>o.value)")
js("document.querySelector('#chip-field').value='Cancelled';closeDialog()")
assert js('snapshot()')==source and not panel.dirty
open_chip();js("document.querySelector('#chip-field').value='Total';document.querySelector('#chip-type').value='Date';document.querySelector('#chip-type').dispatchEvent(new Event('change'))")
assert 'yyyy-MM-dd' in json_js("[...document.querySelector('#chip-formats').options].map(o=>o.value)")
js("document.querySelector('#chip-format').value='yyyy-MM-dd'");click_save()
wait(lambda:panel.dirty)
value=json_js("tagPayload(editor.querySelector('.chip').dataset.comms,'data')")
assert value=={'Extra':{'keep':True},'Id':'Total','Type':'Date','Format':'yyyy-MM-dd'}
js("cmd('undo')");wait(lambda:not panel.dirty);assert js('snapshot()')==source
js("cmd('redo')");wait(lambda:panel.dirty)
# Encoded source stays encoded after edits and clearing optional properties.
load(raw,True);open_chip();js("document.querySelector('#chip-type').value='';document.querySelector('#chip-format').value=''");click_save()
assert js("editor.querySelector('.chip').dataset.encoded")=='true'
assert '&lt;comms-data&gt;' in js('snapshot()')
assert 'Type' not in json_js("tagPayload(editor.querySelector('.chip').dataset.comms,'data')")
# Loop picker finds Id regardless of key order and retains body/marker metadata.
context={'fields':[{'name':'Amount','scope':'AT field'},{'name':'LineTotal','scope':'iteration: Lines'}],
         'iterations':[{'name':'Lines','path':'$.rows','fields':[{'name':'LineTotal','path':'$.amount'}],'condition':'@.active'}, {'name':'Other "Loop"','path':'$.other','fields':[]}],
         'contents':['BillHeader','BillFooter']}
js('context('+json.dumps(context)+')')
loop='<comms-loop><comms-data>$Data'+json.dumps({'Extra':'preserved','Id':'Lines'})+'</comms-data><b>Body unchanged</b></comms-loop>'
source=load(loop);open_chip()
assert 'LineTotal ($.amount)' in js("document.querySelector('#loop-context').textContent")
assert not js("document.querySelector('#loop-picker').hidden")
js("document.querySelector('#loop-name').value='Other \"Loop\"'");click_save()
updated=js("editor.querySelector('.chip').dataset.comms")
assert '<b>Body unchanged</b>' in updated and 'preserved' in updated
assert 'Other \\"Loop\\"' in updated
open_chip();js("document.querySelector('#loop-source-toggle').click();document.querySelector('#loop-source').value='<comms-loop>transformed body</comms-loop>'");click_save()
assert js("editor.querySelector('.chip').dataset.comms")=='<comms-loop>transformed body</comms-loop>'
open_chip();assert js("document.querySelector('#loop-picker').hidden")
js("document.querySelector('#loop-source').value='invalid'");click_save()
assert js("document.querySelector('#chip-error').textContent")
assert js("document.querySelector('#dialog').classList.contains('open')")
js('closeDialog()')
# Condition Text fields/chips, per-target drafts, and Content choices.
cond='<comms-cond>$Cond'+json.dumps({'Condition':'@.ok','Text':'Hello ','Extra':{'keep':1}})+'</comms-cond>'
source=load(cond);open_chip()
assert js("document.querySelectorAll('#cond-fields button').length")==2
js("document.querySelectorAll('#cond-fields button')[1].click()")
assert js("document.querySelector('#cond-text .chip').textContent")=='$LineTotal'
js("document.querySelector('#cond-kind').value='Content';document.querySelector('#cond-kind').dispatchEvent(new Event('change'))")
assert json_js("[...document.querySelector('#cond-contents').options].map(o=>o.value)")==['BillHeader','BillFooter']
js("document.querySelector('#cond-content').value='BillHeader';document.querySelector('#cond-kind').value='Text';document.querySelector('#cond-kind').dispatchEvent(new Event('change'))")
assert '$Data' in js("conditionTextValue(document.querySelector('#cond-text'))")
click_save()
value=json_js("tagPayload(editor.querySelector('.chip').dataset.comms,'cond')")
assert value['Text']=='Hello <comms-data>$Data{"Id":"LineTotal"}</comms-data>' and value['Extra']=={'keep':1}
open_chip();js("document.querySelector('#cond-kind').value='Content';document.querySelector('#cond-kind').dispatchEvent(new Event('change'));document.querySelector('#cond-content').value='BillFooter'");click_save()
value=json_js("tagPayload(editor.querySelector('.chip').dataset.comms,'cond')")
assert value['Content']=='BillFooter' and 'Text' not in value and value['Extra']=={'keep':1}
# Typing $ offers scoped fields and replaces the partial token at the caret.
load(cond);open_chip()
js("const target=document.querySelector('#cond-text');target.textContent='Hello $Line';const range=document.createRange();range.selectNodeContents(target);range.collapse(false);window.getSelection().removeAllRanges();window.getSelection().addRange(range);target.dispatchEvent(new Event('input'));target.dispatchEvent(new KeyboardEvent('keyup',{key:'e'}))")
assert js("document.querySelector('#cond-field-filter').value")=='Line'
assert js("document.querySelectorAll('#cond-fields button').length")==1
js("document.querySelector('#cond-fields button').click()");click_save()
value=json_js("tagPayload(editor.querySelector('.chip').dataset.comms,'cond')")
assert value['Text']=='Hello <comms-data>$Data{"Id":"LineTotal"}</comms-data>'
# Multiline condition text does not gain an artificial final newline.
load(cond);open_chip()
js("document.querySelector('#cond-text').innerHTML='First<div>Second</div>'")
assert js("conditionTextValue(document.querySelector('#cond-text'))")=='First\nSecond'
js("document.querySelector('#cond-text').innerHTML='First<div>Second</div><div><br></div>'")
assert js("conditionTextValue(document.querySelector('#cond-text'))")=='First\nSecond\n'
js('closeDialog()')
# Editing an encoded condition with a nested data token retains its encoding.
nested='<comms-cond>$Cond'+json.dumps({'Condition':'@.ok','Text':'Before <comms-data>$Data{"Id":"Amount"}</comms-data> after','Extra':2})+'</comms-cond>'
load(nested,True);open_chip()
assert js("document.querySelectorAll('#cond-text .chip').length")==1
js("document.querySelector('#cond-rule').value='@.updated'");click_save()
value=json_js("tagPayload(editor.querySelector('.chip').dataset.comms,'cond')")
assert value['Extra']==2 and value['Condition']=='@.updated'
assert '<comms-data>$Data{"Id":"Amount"}</comms-data>' in value['Text']
assert js("editor.querySelector('.chip').dataset.encoded")=='true'
# Unsupported data forms have a source fallback, with wrapper validation.
load('<comms-data>custom transform</comms-data>');open_chip()
assert js("document.querySelector('#chip-source').value")=='<comms-data>custom transform</comms-data>'
js("document.querySelector('#chip-source').value='missing wrapper'");click_save()
assert js("document.querySelector('#chip-error').textContent")
js("document.querySelector('#chip-source').value='<comms-data>updated transform</comms-data>'");click_save()
assert js("editor.querySelector('.chip').dataset.comms")=='<comms-data>updated transform</comms-data>'
# Required condition/target fields reject Save without modifying the document.
source=load(cond);open_chip()
js("document.querySelector('#cond-rule').value=''");click_save()
assert js("document.querySelector('#chip-error').textContent")=='Condition is required.'
assert js('snapshot()')==source
js("document.querySelector('#cond-rule').value='@.ok';document.querySelector('#cond-text').textContent=''");click_save()
assert js("document.querySelector('#chip-error').textContent")=='Text is required.'
assert js('snapshot()')==source
js('closeDialog()')
# Encoded loops with inner loops remain a single intact outer chip.
nested_loop='<comms-loop><b>Outer</b><comms-loop>Inner</comms-loop></comms-loop>'
load(nested_loop,True);open_chip()
assert js("document.querySelector('#loop-source').value")==nested_loop
js('closeDialog()')
# Python context includes actual Content browser names.
QTreeWidgetItem(panel.browser,['ActualContent','HTML'])
rich.set_context(context['fields'],context['iterations'])
assert json_js('contents')==['ActualContent']
# Reloading source closes stale editors; delayed Save cannot replace fresh source.
load(raw);open_chip();panel.source.setPlainText('<p>New source</p>')
wait(lambda:js('snapshot()')=='<p>New source</p>')
assert not js("document.querySelector('#dialog').classList.contains('open')")
click_save();assert js('snapshot()')=='<p>New source</p>'
# Original cell/table property choices include both alignment controls.
table_source='<table data-keep="yes" style="margin:4px"><tr><td style="color:red">Cell</td><td>Other</td></tr></table>'
panel.source.setPlainText(table_source);wait(lambda:js('snapshot()')==table_source)
panel.baseline=panel.snapshot()
js("selectCell(editor.querySelector('td'));cellProperties()")
assert json_js("[...document.querySelector('#p-align-choices').options].map(o=>o.value)")==['left','center','right']
assert json_js("[...document.querySelector('#p-vertical-choices').options].map(o=>o.value)")==['top','middle','bottom']
js("document.querySelector('#p-width').value='100px';document.querySelector('#p-height').value='20px';document.querySelector('#p-padding').value='3px';document.querySelector('#p-background').value='#fff';document.querySelector('#p-border').value='1px solid #000';document.querySelector('#p-align').value='right';document.querySelector('#p-vertical').value='middle';document.querySelector('#p-save').click()")
assert js("editor.querySelector('td').style.textAlign")=='right'
assert js("editor.querySelector('td').style.verticalAlign")=='middle'
assert js("editor.querySelector('td').style.color")=='red'
assert js("editor.querySelector('table').dataset.keep")=='yes'
assert js("editor.querySelector('table').style.margin")=='4px'
js("cmd('undo')");wait(lambda:not panel.dirty);assert js('snapshot()')==table_source
js("selectCell(editor.querySelector('td'));tableProperties();document.querySelector('#p-align').value='center';document.querySelector('#p-save').click()")
assert js("editor.querySelector('table').style.textAlign")=='center'
js("selectCell(editor.querySelector('td'));cellProperties();document.querySelector('#p-align').value='left';closeDialog()")
assert js("editor.querySelector('td').style.textAlign")==''
# Capture one actual condition editor for visual review.
load(cond);open_chip();app.processEvents();
assert js("document.querySelector('#dialog-actions').getBoundingClientRect().bottom<=innerHeight"), 'Save and Cancel must fit in the visible editor'
rich.grab().save('/private/tmp/atool-condition-chip-editor.png');js('closeDialog()')
panel.baseline=panel.snapshot();window.close();temporary.cleanup()
print('Embedded chip editor checks passed')
