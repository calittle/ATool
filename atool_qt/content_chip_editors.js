// Editors for Comms tags. Draft controls never mutate the document before Save.
const dataFormatPresets = {
    '': [], String: [], Decimal: ['$#,##0.00', '#,##0.00', '($#,##0.00)', '#,##0.00;(#,##0.00);0.00'],
    Date: ['MM-dd-yyyy', 'MM/dd/yyyy', 'MMM dd, yyyy', 'yyyy-MM-dd'],
    DateTime: ["yyyy-MM-dd-'T'-HH-mm-ss-SSS z"], Image: [], PDF: []
};
function tagPayload(raw, kind) {
    const marker = kind === 'data' ? 'Data' : 'Cond';
    const match = raw.match(new RegExp('^<comms-' + kind + '>\\s*\\$' + marker + '(\\{[\\s\\S]*\\})\\s*</comms-' + kind + '>$', 'i'));
    if (!match) return null;
    try { const value = JSON.parse(match[1]); return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }
    catch (_) { return null; }
}
function chipActions(extra='') {
    return '<div id="dialog-actions"><button type="button" data-command="closeDialog()">Cancel</button>' + extra + '<button type="button" id="chip-save">Save</button></div>';
}
function fillSuggestions(list, values) {
    list.replaceChildren();
    [...new Set(values)].forEach(value => { const option=document.createElement('option'); option.value=value; list.append(option); });
}
function commitChip(chip, raw, revision) {
    if (revision !== generation || !editor.contains(chip)) { closeDialog(); return; }
    chip.replaceWith(makeChip(raw, chip.dataset.encoded === 'true'));
    closeDialog();
    notify();
}
function sourceChipEditor(chip, kind, raw, revision) {
    const card=document.getElementById('card');
    card.innerHTML='<h2>Edit ' + kind + ' source</h2><textarea id="chip-source" rows="10" spellcheck="false"></textarea><p id="chip-error" role="alert"></p>'+chipActions();
    card.querySelector('#chip-source').value=raw;
    card.querySelector('#chip-save').onclick=()=>{
        const next=card.querySelector('#chip-source').value.trim();
        if (!new RegExp('^<comms-'+kind+'>[\\s\\S]*</comms-'+kind+'>$','i').test(next)) {
            card.querySelector('#chip-error').textContent='Use <comms-'+kind+'> and </comms-'+kind+'> around the source.';
            return;
        }
        commitChip(chip,next,revision);
    };
}
function editLoopChip(chip, raw, revision) {
    const card=document.getElementById('card');
    const marker=raw.match(/<comms-data>\s*\$Data\{[\s\S]*?\}\s*<\/comms-data>/i);
    const value=marker ? tagPayload(marker[0],'data') : null;
    const canPick=Boolean(value && iterations.length);
    let sourceMode=!canPick;
    card.innerHTML='<h2>Edit loop</h2><div id="loop-picker"><label>AT loop</label><select id="loop-name"></select><p id="loop-context"></p></div><div id="loop-source-area"><label>Loop source</label><textarea id="loop-source" rows="10" spellcheck="false"></textarea><p>Use source editing for transforms or another loop form.</p></div><p id="chip-error" role="alert"></p>'+chipActions('<button type="button" id="loop-source-toggle">Edit Source HTML…</button>');
    const select=card.querySelector('#loop-name'), source=card.querySelector('#loop-source');
    iterations.forEach(item=>{const option=document.createElement('option');option.value=item.name;option.textContent=item.name;select.append(option);});
    if (value && iterations.some(item=>item.name===value.Id)) select.value=value.Id;
    source.value=raw;
    const showContext=()=>{
        const item=iterations.find(item=>item.name===select.value);
        card.querySelector('#loop-context').textContent=item ? 'Path: '+(item.path||'(not set)')+'\nFields: '+((item.fields||[]).map(field=>field.name+(field.path?' ('+field.path+')':'')).join(', ')||'(no iteration fields)')+(item.condition?'\nCondition: '+item.condition:'') : '';
    };
    select.onchange=showContext;showContext();
    const showMode=()=>{
        card.querySelector('#loop-picker').hidden=sourceMode;
        card.querySelector('#loop-source-area').hidden=!sourceMode;
        card.querySelector('#loop-source-toggle').textContent=sourceMode?'Use AT Picker':'Edit Source HTML…';
        card.querySelector('#loop-source-toggle').disabled=!canPick;
    };
    card.querySelector('#loop-source-toggle').onclick=()=>{sourceMode=!sourceMode;showMode();};showMode();
    card.querySelector('#chip-save').onclick=()=>{
        let next=source.value.trim();
        if (!sourceMode) {
            const selected=iterations.find(item=>item.name===select.value);
            if (!selected || !value) return;
            const updated='<comms-data>$Data'+JSON.stringify({...value,Id:selected.name})+'</comms-data>';
            next=raw.slice(0,marker.index)+updated+raw.slice(marker.index+marker[0].length);
        }
        if (!/^<comms-loop>[\s\S]*<\/comms-loop>$/i.test(next)) {
            card.querySelector('#chip-error').textContent='Loop source must be wrapped in <comms-loop> and </comms-loop>.';return;
        }
        commitChip(chip,next,revision);
    };
}
function editDataChip(chip, value, revision) {
    const card=document.getElementById('card');
    card.innerHTML='<h2>Edit data field</h2><label>Field</label><input id="chip-field" list="chip-fields"><datalist id="chip-fields"></datalist><label>Type</label><select id="chip-type"></select><label>Format</label><input id="chip-format" list="chip-formats"><datalist id="chip-formats"></datalist><p>Choose a format suggestion or enter a different valid format.</p><p id="chip-error" role="alert"></p>'+chipActions();
    card.querySelector('#chip-field').value=value.Id||'';
    fillSuggestions(card.querySelector('#chip-fields'),fields.map(field=>field.name));
    const type=card.querySelector('#chip-type');
    ['', 'String', 'Decimal', 'Date', 'DateTime', 'Image', 'PDF'].forEach(name=>{const option=document.createElement('option');option.value=name;option.textContent=name||'(none)';type.append(option);});
    if (value.Type && !Object.hasOwn(dataFormatPresets,value.Type)) {const option=document.createElement('option');option.value=value.Type;option.textContent=value.Type;type.append(option);}
    type.value=value.Type||'';
    card.querySelector('#chip-format').value=value.Format||'';
    const showFormats=()=>fillSuggestions(card.querySelector('#chip-formats'),dataFormatPresets[type.value]||[]);
    type.onchange=showFormats;showFormats();
    card.querySelector('#chip-save').onclick=()=>{
        const next={...value,Id:card.querySelector('#chip-field').value.trim()};
        if (!next.Id) {card.querySelector('#chip-error').textContent='Field is required.';return;}
        if (type.value) next.Type=type.value; else delete next.Type;
        const format=card.querySelector('#chip-format').value;
        if (format.trim()) next.Format=format; else delete next.Format;
        commitChip(chip,'<comms-data>$Data'+JSON.stringify(next)+'</comms-data>',revision);
    };
}
function conditionTextValue(target) {
    const copy=target.cloneNode(true);
    copy.querySelectorAll('.chip[data-comms]').forEach(chip=>chip.replaceWith(document.createTextNode(chip.dataset.comms)));
    // Browser-generated block nodes separate lines without an implicit final newline.
    const children=parent=>[...parent.childNodes].map((node,index)=>{
        if(node.nodeType===Node.TEXT_NODE)return node.nodeValue;
        if(node.tagName==='BR')return '\n';
        const block=/^(DIV|P)$/.test(node.tagName);
        const emptyLine=block&&node.childNodes.length===1&&node.firstChild.nodeName==='BR';
        return (block&&index>0?'\n':'')+(emptyLine?'':children(node));
    }).join('');
    return children(copy);
}
function editConditionChip(chip, value, revision) {
    const card=document.getElementById('card');
    let kind=Object.hasOwn(value,'Text')?'Text':'Content';
    const drafts={Text:String(value.Text||''),Content:String(value.Content||'')};
    card.innerHTML='<h2>Edit condition</h2><label>Condition</label><input id="cond-rule"><label>Target type</label><select id="cond-kind"><option>Text</option><option>Content</option></select><label id="cond-target-label"></label><div id="cond-text" class="text-target" contenteditable="true"></div><input id="cond-content" list="cond-contents"><datalist id="cond-contents"></datalist><div id="cond-field-tools"><label>Insert field</label><input id="cond-field-filter" placeholder="Find an AT or iteration field"><div id="cond-fields"></div></div><p id="chip-error" role="alert"></p>'+chipActions();
    card.querySelector('#cond-rule').value=value.Condition||'';
    const select=card.querySelector('#cond-kind'), target=card.querySelector('#cond-text'), content=card.querySelector('#cond-content');
    select.value=kind;
    target.textContent=drafts.Text;normalizeChips(target);
    content.value=drafts.Content;
    fillSuggestions(card.querySelector('#cond-contents'),contents);
    let savedRange=null;
    const remember=()=>{
        const selection=window.getSelection();
        if(selection.rangeCount&&target.contains(selection.getRangeAt(0).commonAncestorContainer)){
            savedRange=selection.getRangeAt(0).cloneRange();
            const node=savedRange.startContainer;
            const previous=node.nodeType===Node.ELEMENT_NODE?node.childNodes[savedRange.startOffset-1]:null;
            if(savedRange.collapsed&&previous&&previous.nodeType===Node.TEXT_NODE){savedRange.setStart(previous,previous.nodeValue.length);savedRange.collapse(true);}
        }
    };
    target.addEventListener('keyup',remember);target.addEventListener('mouseup',remember);target.addEventListener('input',remember);
    const filter=card.querySelector('#cond-field-filter'), choices=card.querySelector('#cond-fields');
    const showFields=()=>{
        const query=filter.value.trim().toLowerCase();choices.replaceChildren();
        fields.filter(field=>(field.name+' '+field.scope).toLowerCase().includes(query)).forEach(field=>{
            const button=document.createElement('button');button.type='button';button.textContent=field.name+(field.scope?' — '+field.scope:'');
            button.onclick=()=>{
                const range=savedRange&&target.contains(savedRange.commonAncestorContainer)?savedRange:document.createRange();
                if (!savedRange || !target.contains(range.commonAncestorContainer)) {range.selectNodeContents(target);range.collapse(false);}
                if (range.collapsed && range.startContainer.nodeType===Node.TEXT_NODE) {
                    const before=range.startContainer.nodeValue.slice(0,range.startOffset);
                    const typed=before.match(/\$([A-Za-z0-9_]*)$/);
                    if (typed) range.setStart(range.startContainer,range.startOffset-typed[0].length);
                }
                range.deleteContents();
                const token=makeChip('<comms-data>$Data'+JSON.stringify({Id:field.name})+'</comms-data>',true);
                range.insertNode(token);range.setStartAfter(token);range.collapse(true);
                const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);savedRange=range.cloneRange();target.focus();
            };choices.append(button);
        });
    };
    filter.oninput=showFields;showFields();
    const offerTypedField=()=>{
        remember();
        if (!savedRange || savedRange.startContainer.nodeType!==Node.TEXT_NODE) return;
        const before=savedRange.startContainer.nodeValue.slice(0,savedRange.startOffset);
        const match=before.match(/\$([A-Za-z0-9_]*)$/);
        if (match) {
            filter.value=match[1];showFields();
        }
    };
    target.addEventListener('input',offerTypedField);
    target.addEventListener('keydown',event=>{
        if (event.ctrlKey && event.code==='Space') {event.preventDefault();offerTypedField();filter.focus();}
    });
    const showKind=()=>{target.hidden=kind!=='Text';content.hidden=kind!=='Content';card.querySelector('#cond-field-tools').hidden=kind!=='Text';card.querySelector('#cond-target-label').textContent=kind+':';};
    select.onchange=()=>{
        drafts[kind]=kind==='Text'?conditionTextValue(target):content.value;
        kind=select.value;
        if(kind==='Text'){target.textContent=drafts.Text;normalizeChips(target);savedRange=null;}else content.value=drafts.Content;
        showKind();
    };showKind();
    card.querySelector('#chip-save').onclick=()=>{
        const next={...value,Condition:card.querySelector('#cond-rule').value.trim()};delete next.Text;delete next.Content;
        next[kind]=kind==='Text'?conditionTextValue(target):content.value.trim();
        if(!next.Condition||!next[kind].trim()){card.querySelector('#chip-error').textContent=!next.Condition?'Condition is required.':kind+' is required.';return;}
        commitChip(chip,'<comms-cond>$Cond'+JSON.stringify(next)+'</comms-cond>',revision);
    };
}
function editChip(chip) {
    const raw=chip.dataset.comms, revision=generation;
    if (/^<comms-loop>/i.test(raw)) editLoopChip(chip,raw,revision);
    else {
        const kind=/^<comms-cond>/i.test(raw)?'cond':'data';
        const value=tagPayload(raw,kind);
        if (!value) sourceChipEditor(chip,kind,raw,revision);
        else if (kind==='cond') editConditionChip(chip,value,revision);
        else editDataChip(chip,value,revision);
    }
    document.getElementById('dialog').classList.add('open');
    document.getElementById('card').scrollTop=0;
}
