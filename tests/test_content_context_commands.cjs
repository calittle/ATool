// Headless command/eligibility checks. The real WebEngine smoke check lives in
// check_qt_content_context_menus.py; this test needs only Node's standard library.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..', 'atool_qt');
const html = fs.readFileSync(path.join(root, 'content_editor.html'), 'utf8');
const code = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n')
    .replace('/* CHIP_EDITORS */', () => fs.readFileSync(path.join(root, 'content_chip_editors.js'), 'utf8'));
const events = [];
const selection = {rangeCount: 0, removeAllRanges() {}, addRange(range) {this.range = range;}};
const elements = new Map();
const element = id => {
    if (!elements.has(id)) elements.set(id, {
        addEventListener() {}, contains(node) {return Boolean(node?.connected);},
        focus() {events.push('focus');}, classList: {contains() {return false;}},
    });
    return elements.get(id);
};
const document = {
    getElementById: element, querySelector: element, addEventListener() {},
    createRange() {return {collapsed: false, selectNode(node) {this.commonAncestorContainer = node.parent;},
        selectNodeContents(node) {this.commonAncestorContainer = node;}, collapse() {this.collapsed = true;}};},
    caretRangeFromPoint() {return null;},
};
const sandbox = vm.createContext({
    document, window: {addEventListener() {}, getSelection() {return selection;}},
    MutationObserver: class {observe() {}},
    QWebChannel: class {constructor(transport, callback) {callback({objects: {content: {ready() {}}}});}},
    qt: {webChannelTransport: {}}, events,
});
vm.runInContext(code, sandbox); // Also parses the complete shipped editor scripts.
const js = expression => vm.runInContext(expression, sandbox);

// A rectangular neighboring cell may merge; missing or incompatible spans may not.
const section = {};
const a = {parentElement: {parentElement: section}};
const b = {parentElement: {parentElement: section}};
const positions = new Map([[a, {row: 0, col: 0, w: 1, h: 1}], [b, {row: 0, col: 1, w: 1, h: 1}]]);
sandbox.fixture = {cell: a, layout: {positions, grid: [[a, b]]}};
js('activeCell=fixture.cell;table=()=>Boolean(activeCell);tableGrid=()=>fixture.layout');
assert.equal(js('canMergeContext("right")'), true);
assert.equal(js('canMergeContext("left")'), false);
assert.equal(js('canMergeContext("up")'), false);
positions.get(b).h = 2;
assert.equal(js('canMergeContext("right")'), false);
positions.get(b).h = 1;

// Context preparation identifies the actual chip, preserves its markup, and
// does not invoke an edit or add undo history merely by opening a menu.
const parent = {connected: true};
const chip = {parent, classList: {contains(name) {return name === 'data';}}, dataset: {comms: '<comms-data>$Data{"Id":"Amount"}</comms-data>'}};
sandbox.fixture.target = {closest(selector) {return selector.startsWith('.chip') ? chip : null;}};
js('selectCell=cell=>{activeCell=cell;}');
const description = js('prepareContext(fixture.target,12,24)');
assert.equal(description.chipKind, 'data');
assert.equal(description.chipMarkup, chip.dataset.comms);
assert.equal(description.selection, true);
assert.equal(js('undoStack.length'), 0);
assert.deepEqual(events, []);

// Revision and connection checks reject stale commands before selection changes.
assert.equal(js('restoreContext(generation+1,contextRequest)'), false);
assert.equal(js('restoreContext(generation,contextRequest+1)'), false);
// The chip itself must still be connected as well as its range's parent.
chip.connected = true;
assert.equal(js('restoreContext(generation,contextRequest)'), true);
chip.connected = false;
assert.equal(js('restoreContext(generation,contextRequest)'), false);
chip.connected = true;

// Dispatch uses existing edit/table functions and notifies once per mutation.
js('notify=()=>events.push("notify");addRow=above=>events.push(above?"rowAbove":"rowBelow");undoRich=()=>events.push("undo");editChip=()=>events.push("editChip")');
events.length = 0;
assert.equal(js('runContextCommand("rowAbove",generation,contextRequest)'), true);
assert.deepEqual(events, ['focus', 'rowAbove', 'notify']);
events.length = 0;
js('runContextCommand("undo",generation,contextRequest)');
assert.deepEqual(events, ['focus', 'undo']);
events.length = 0;
js('runContextCommand("editChip",generation,contextRequest)');
assert.deepEqual(events, ['focus', 'editChip']);
events.length = 0;
assert.equal(js('runContextCommand("rowAbove",generation+1,contextRequest)'), false);
assert.deepEqual(events, []);
console.log('Content context commands: target metadata, merge eligibility, revision guards, and dispatch passed.');
