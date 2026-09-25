#!/usr/bin/env python3
"""Native WebKit editor process used by ATool's unified Content editor.

The process boundary keeps Cocoa's WebView event loop independent from Tk's
event loop.  It receives an input JSON file and writes output JSON only when
the user explicitly saves.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import webview


EDITOR_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><style>
body { margin:0; font:14px -apple-system, BlinkMacSystemFont, sans-serif; color:#1f2937; }
#bar { display:flex; gap:6px; align-items:center; padding:8px 10px; border-bottom:1px solid #d1d5db; background:#f8fafc; position:sticky; top:0; z-index:2; }
#bar .spacer { flex:1; } button { border:1px solid #cbd5e1; border-radius:5px; background:white; padding:5px 9px; cursor:pointer; } button:hover { background:#eff6ff; }
#editor { min-height:calc(100vh - 54px); box-sizing:border-box; padding:22px; outline:none; } #editor:focus { box-shadow:inset 0 0 0 2px #bfdbfe; }
table { border-collapse:collapse; } td, th { min-width:32px; min-height:18px; padding:0; vertical-align:top; outline:1px solid #cbd5e1; outline-offset:-1px; } td.active, th.active { outline:2px solid #2563eb; outline-offset:-2px; }
.chip { display:inline-block; padding:1px 5px; margin:0 2px; border-radius:4px; background:#e0f2fe; color:#075985; font:12px ui-monospace, SFMono-Regular, Menlo, monospace; cursor:pointer; user-select:none; } .chip.data { background:#f3e8ff; color:#6d28d9; } .chip.loop { background:#ffedd5; color:#7c2d12; }
#dialog { position:fixed; inset:0; display:none; place-items:center; background:#0004; z-index:5; } #dialog.open { display:grid; } #card { width:min(520px, calc(100vw - 40px)); background:white; border-radius:9px; box-shadow:0 18px 48px #0005; padding:18px; } #card h2 { margin:0 0 14px; font-size:16px; } #card input { width:100%; box-sizing:border-box; padding:7px; border:1px solid #94a3b8; border-radius:4px; } #choices { max-height:210px; overflow:auto; border:1px solid #cbd5e1; border-radius:4px; margin-top:5px; } #choices button { display:block; width:100%; text-align:left; border:0; border-radius:0; } #dialog-actions { display:flex; justify-content:flex-end; gap:7px; margin-top:16px; }
#source { width:100%; height:calc(100vh - 54px); box-sizing:border-box; border:0; padding:18px; font:12px ui-monospace, SFMono-Regular, Menlo, monospace; display:none; outline:none; }
</style></head><body>
<div id="bar"><button type="button" onclick="cmd('bold')"><b>B</b></button><button type="button" onclick="cmd('italic')"><i>I</i></button><button type="button" onclick="cmd('underline')"><u>U</u></button><button type="button" onclick="insertField()">Field…</button><button type="button" onclick="insertTable()">Table</button><button type="button" onclick="addRow(true)">Row ↑</button><button type="button" onclick="addRow(false)">Row ↓</button><button type="button" onclick="addColumn(true)">Column ←</button><button type="button" onclick="addColumn(false)">Column →</button><button type="button" onclick="splitCell(false)">Split ↔</button><button type="button" onclick="splitCell(true)">Split ↕</button><button type="button" onclick="mergeLeft()">Merge ←</button><button type="button" onclick="mergeRight()">Merge →</button><button type="button" onclick="mergeUp()">Merge ↑</button><button type="button" onclick="mergeDown()">Merge ↓</button><button type="button" onclick="cellProperties()">Cell style…</button><button type="button" onclick="tableProperties()">Table style…</button><button type="button" onclick="toggleSource()">Source</button><span class="spacer"></span><button type="button" onclick="cancel()">Cancel</button><button type="button" onclick="save()">Save</button></div>
<div id="editor" contenteditable="true"></div><textarea id="source" spellcheck="false"></textarea><div id="dialog"><div id="card"></div></div>
<script>
let sourceMode=false, activeCell=null, fields=[], iterations=[];
const editor=document.getElementById('editor'), source=document.getElementById('source');
function cmd(name){ document.execCommand(name,false,null); editor.focus(); }
function makeChip(raw){ const chip=document.createElement('span'); chip.className='chip '+(raw.startsWith('<comms-data')?'data':raw.startsWith('<comms-loop')?'loop':''); chip.contentEditable='false'; chip.dataset.comms=raw; const field=raw.match(/\$Data\s*\{\s*"Id"\s*:\s*"([^"\\]+)"/); const cond=raw.match(/\$Cond\s*\{.*?"(?:Text|Content)"\s*:\s*"([^"\\]*)/); const nested=raw.startsWith('<comms-cond')&&field; chip.textContent=raw.startsWith('<comms-data')&&field?'$'+field[1]:raw.startsWith('<comms-loop')?'↻ Loop':'◆ '+(nested?'$'+field[1]:(cond?cond[1]:'Condition')); return chip; }
function normalizeChips(root=editor){ const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT); const nodes=[]; while(walker.nextNode())nodes.push(walker.currentNode); nodes.forEach(node=>{const raw=node.nodeValue; const re=/(<comms-(?:data|cond|loop)>[\s\S]*?<\/comms-(?:data|cond|loop)>)/gi; let match,last=0, fragment=null; while((match=re.exec(raw))){ fragment ||= document.createDocumentFragment(); fragment.append(document.createTextNode(raw.slice(last,match.index)),makeChip(match[1])); last=match.index+match[1].length; } if(fragment){fragment.append(document.createTextNode(raw.slice(last)));node.replaceWith(fragment);} }); }
function closeDialog(){document.getElementById('dialog').classList.remove('open');}
function insertChip(chip){const range=window.getSelection().rangeCount?window.getSelection().getRangeAt(0):null; if(range){range.deleteContents();range.insertNode(chip);range.setStartAfter(chip);range.collapse(true);window.getSelection().removeAllRanges();window.getSelection().addRange(range);}else editor.append(chip); editor.focus();}
function insertField(){ const card=document.getElementById('card'), dialog=document.getElementById('dialog'); card.innerHTML='<h2>Insert data field</h2><input id="field-filter" placeholder="Search fields"><div id="choices"></div><div id="dialog-actions"><button type="button" onclick="closeDialog()">Cancel</button></div>'; const filter=card.querySelector('#field-filter'), choices=card.querySelector('#choices'); const render=()=>{const q=filter.value.toLowerCase();choices.innerHTML='';fields.filter(f=>(f.name+' '+f.scope).toLowerCase().includes(q)).slice(0,100).forEach(field=>{const b=document.createElement('button');b.type='button';b.textContent=field.name+(field.scope?' — '+field.scope:'');b.onclick=()=>{insertChip(makeChip('<comms-data>$Data{"Id":"'+field.name.replaceAll('"','')+'"}</comms-data>'));closeDialog()};choices.append(b)});};filter.oninput=render;render();dialog.classList.add('open');filter.focus();}
function editChip(chip){ const raw=chip.dataset.comms, card=document.getElementById('card'), dialog=document.getElementById('dialog'); if(raw.startsWith('<comms-loop')){card.innerHTML='<h2>Edit loop</h2><label>Assembly-template loop</label><select id="loop-name"></select><div id="dialog-actions"><button type="button" onclick="closeDialog()">Cancel</button><button type="button" id="chip-save">Save</button></div>';const select=card.querySelector('#loop-name');iterations.forEach(item=>{const option=document.createElement('option');option.value=item.name;option.textContent=item.name+(item.path?' — '+item.path:'');select.append(option)});const existing=(raw.match(/\$Data\s*\{\s*"Id"\s*:\s*"([^"\\]+)"/)||[])[1];select.value=existing||select.value;card.querySelector('#chip-save').onclick=()=>{const name=select.value;if(!name)return;const next=raw.replace(/(\$Data\s*\{\s*"Id"\s*:\s*")[^"\\]+/, '$1'+name);chip.replaceWith(makeChip(next));closeDialog();};dialog.classList.add('open');return;} const data=raw.match(/^<comms-data>\$Data(\{[\s\S]*\})<\/comms-data>$/i); const cond=raw.match(/^<comms-cond>\$Cond(\{[\s\S]*\})<\/comms-cond>$/i); let value={};try{value=JSON.parse((data||cond||[])[1])}catch(_){alert('This chip has nested markup that needs the Source editor. Its original markup is preserved.');return;} if(cond){const target=value.Content!==undefined?'Content':'Text';card.innerHTML='<h2>Edit condition</h2><label>Condition</label><input id="cond-rule"><label>Target type</label><select id="cond-kind"><option>Text</option><option>Content</option></select><label>Target</label><input id="cond-target"><div id="dialog-actions"><button type="button" onclick="closeDialog()">Cancel</button><button type="button" id="chip-save">Save</button></div>';card.querySelector('#cond-rule').value=value.Condition||'';card.querySelector('#cond-kind').value=target;card.querySelector('#cond-target').value=value[target]||'';card.querySelector('#chip-save').onclick=()=>{const kind=card.querySelector('#cond-kind').value,next={Condition:card.querySelector('#cond-rule').value.trim()};next[kind]=card.querySelector('#cond-target').value;chip.replaceWith(makeChip('<comms-cond>$Cond'+JSON.stringify(next)+'</comms-cond>'));closeDialog();};dialog.classList.add('open');return;} if(!data)return;card.innerHTML='<h2>Edit data field</h2><label>Field</label><input id="chip-field"><label>Type</label><input id="chip-type" placeholder="Optional"><label>Format</label><input id="chip-format" placeholder="Optional"><div id="dialog-actions"><button type="button" onclick="closeDialog()">Cancel</button><button type="button" id="chip-save">Save</button></div>';card.querySelector('#chip-field').value=value.Id||'';card.querySelector('#chip-type').value=value.Type||'';card.querySelector('#chip-format').value=value.Format||'';card.querySelector('#chip-save').onclick=()=>{const next={...value,Id:card.querySelector('#chip-field').value.trim()};if(!next.Id)return;if(card.querySelector('#chip-type').value.trim())next.Type=card.querySelector('#chip-type').value.trim();else delete next.Type;if(card.querySelector('#chip-format').value.trim())next.Format=card.querySelector('#chip-format').value.trim();else delete next.Format;chip.replaceWith(makeChip('<comms-data>$Data'+JSON.stringify(next)+'</comms-data>'));closeDialog();};dialog.classList.add('open');card.querySelector('#chip-field').focus();}
function serialize(){ const copy=editor.cloneNode(true); copy.querySelectorAll('.chip[data-comms]').forEach(chip=>chip.replaceWith(document.createTextNode(chip.dataset.comms))); return copy.innerHTML; }
function selectCell(cell){ if(activeCell)activeCell.classList.remove('active'); activeCell=cell; if(cell)cell.classList.add('active'); }
editor.addEventListener('click', e => selectCell(e.target.closest('td,th')));
editor.addEventListener('dblclick', e => {const chip=e.target.closest('.chip[data-comms]');if(chip){e.preventDefault();editChip(chip);}});
function insertTable(){ const table=document.createElement('table'); table.innerHTML='<tbody><tr><td style="padding:0px;">Cell</td><td style="padding:0px;">Cell</td></tr></tbody>'; editor.append(table); selectCell(table.querySelector('td')); }
function table(){ return activeCell && activeCell.closest('table'); }
function addRow(above){ const t=table(); if(!t)return; const row=activeCell.parentElement, clone=row.cloneNode(false); [...row.cells].forEach(()=>{const c=document.createElement('td');c.style.padding='0px';c.innerHTML='<br>';clone.append(c)}); if(above)row.before(clone);else row.after(clone); selectCell(clone.cells[Math.min(activeCell.cellIndex,clone.cells.length-1)]); }
function addColumn(left){ const t=table(); if(!t)return; const at=activeCell.cellIndex+(left?0:1); [...t.rows].forEach(row=>{const c=document.createElement('td');c.style.padding='0px';c.innerHTML='<br>';row.insertBefore(c,row.cells[at]||null)}); selectCell(t.rows[activeCell.parentElement.rowIndex].cells[at]); }
function mergeRight(){ if(!activeCell)return; const other=activeCell.nextElementSibling;if(!other)return;activeCell.innerHTML+=(activeCell.innerHTML&&other.innerHTML?'<br>':'')+other.innerHTML;activeCell.colSpan+=other.colSpan;other.remove();selectCell(activeCell); }
function mergeLeft(){if(activeCell&&activeCell.previousElementSibling){selectCell(activeCell.previousElementSibling);mergeRight();}}
function mergeDown(){if(!activeCell)return;const row=activeCell.parentElement,next=row.nextElementSibling;if(!next)return;const index=activeCell.cellIndex,other=next.cells[index];if(!other)return;activeCell.innerHTML+=(activeCell.innerHTML&&other.innerHTML?'<br>':'')+other.innerHTML;activeCell.rowSpan+=other.rowSpan;other.remove();selectCell(activeCell);}
function mergeUp(){if(activeCell&&activeCell.parentElement.previousElementSibling){const row=activeCell.parentElement.previousElementSibling,other=row.cells[activeCell.cellIndex];if(other){selectCell(other);mergeDown();}}}
function splitCell(vertical){if(!activeCell)return;if(vertical){const span=activeCell.rowSpan;if(span<2){addRow(false);return;}activeCell.rowSpan=span-1;const row=activeCell.parentElement.nextElementSibling,copy=document.createElement(activeCell.tagName);copy.style.padding='0px';copy.innerHTML='<br>';row.insertBefore(copy,row.cells[activeCell.cellIndex]||null);selectCell(copy);return;}const span=activeCell.colSpan;if(span<2){addColumn(false);return;}activeCell.colSpan=span-1;const copy=document.createElement(activeCell.tagName);copy.style.padding='0px';copy.innerHTML='<br>';activeCell.after(copy);selectCell(copy);}
function styleDialog(title,target){const card=document.getElementById('card'),dialog=document.getElementById('dialog');const s=target.style;card.innerHTML='<h2>'+title+'</h2><label>Width</label><input id="p-width" value="'+s.width+'" placeholder="e.g. 100px"><label>Height</label><input id="p-height" value="'+s.height+'" placeholder="e.g. 20px"><label>Padding</label><input id="p-padding" value="'+s.padding+'" placeholder="0px"><label>Background</label><input id="p-background" value="'+s.backgroundColor+'" placeholder="#ffffff"><label>Top border</label><input id="p-border" value="'+s.borderTop+'" placeholder="1px solid #000"><div id="dialog-actions"><button type="button" onclick="closeDialog()">Cancel</button><button type="button" id="p-save">Save</button></div>';card.querySelector('#p-save').onclick=()=>{s.width=card.querySelector('#p-width').value;s.height=card.querySelector('#p-height').value;s.padding=card.querySelector('#p-padding').value;s.backgroundColor=card.querySelector('#p-background').value;s.borderTop=card.querySelector('#p-border').value;closeDialog();};dialog.classList.add('open');}
function cellProperties(){if(activeCell)styleDialog('Cell properties',activeCell);}
function tableProperties(){const t=table();if(t)styleDialog('Table properties',t);}
function toggleSource(){ sourceMode=!sourceMode; if(sourceMode){source.value=serialize();editor.style.display='none';source.style.display='block';source.focus()}else{editor.innerHTML=source.value;normalizeChips();source.style.display='none';editor.style.display='block'} }
async function save(){ const html=sourceMode?source.value:serialize(); await window.pywebview.api.save(html); }
async function cancel(){ await window.pywebview.api.cancel(); }
let loaded=false;
async function boot(){ if(loaded || !window.pywebview || !window.pywebview.api)return; loaded=true; const data=await window.pywebview.api.load(); document.title=data.title; fields=data.fields||[];iterations=data.iterations||[]; editor.innerHTML=data.html; normalizeChips(); }
window.addEventListener('pywebviewready', boot);
window.addEventListener('DOMContentLoaded', boot);
setInterval(boot, 100);
</script></body></html>"""


class Bridge:
    def __init__(self, input_path: Path, output_path: Path) -> None:
        self.input_path = input_path
        self.output_path = output_path
        self.payload = json.loads(input_path.read_text(encoding="utf-8"))
        self.window: webview.Window | None = None

    def load(self) -> dict[str, object]:
        fields = self.payload.get("fields", [])
        iterations = self.payload.get("iterations", [])
        return {
            "title": str(self.payload.get("title", "Edit Content")),
            "html": str(self.payload.get("html", "")),
            "fields": fields if isinstance(fields, list) else [],
            "iterations": iterations if isinstance(iterations, list) else [],
        }

    def save(self, html: str) -> None:
        self.output_path.write_text(json.dumps({"saved": True, "html": html}, ensure_ascii=False), encoding="utf-8")
        if self.window:
            self.window.destroy()

    def cancel(self) -> None:
        if self.window:
            self.window.destroy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bridge = Bridge(args.input, args.output)
    bridge.window = webview.create_window(str(bridge.payload.get("title", "Edit Content")), html=EDITOR_HTML, js_api=bridge, width=1080, height=760)
    webview.start(gui="cocoa")


if __name__ == "__main__":
    main()
