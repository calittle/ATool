# ATool 2.0 Qt workspace

The Qt application brings ATool's managers into one dockable workspace. It is
maintained directly on `main`. It is the default application in 2.0.0; the
original Tkinter application remains available through the legacy launchers.
Menus, manager buttons and the status bar follow the original app; the menus
remain visible inside the unified workspace.
The active migration record is `atool_qt/parity_progress.json` and the original
control inventory is `atool_qt/parity_inventory.json`.

## Run

Create the local environment if needed, then install the Qt dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-qt.txt
.venv/bin/python ATool_Qt.py
```

On macOS, double-click `Run_ATool_Qt.command`. On Windows, create the environment
with `py -3 -m venv .venv`, install with
`.venv\Scripts\python -m pip install -r requirements-qt.txt`, then use
`Run_ATool_Qt.bat`.

The workspace starts empty. Open a package with the menu or pass its folder,
manifest, or Assembly Template:

```sh
.venv/bin/python ATool_Qt.py --package /path/to/package/manifest.json
.venv/bin/python ATool_Qt.py --package /path/to/AssemblyTemplate.json --data /path/to/input.json
```

`--data` requires `--package`.
Open Session restores the last package, data file and Comms alias; when no Qt
session exists, it can read the original app's saved session.

## Workspace and managers

The default layout puts Documents on the left, Layouts in the middle, and Fields
on the right. Clause Manager and Data Browser are tabs alongside Fields. Content
Manager opens as a central tab alongside Layouts. Managers can be dragged, docked,
tabbed, hidden and detached. Window menu controls reopen managers; Arrange restores
the default. View offers panel visibility and alternative layouts. Qt stores
panel positions, tabs, visibility and splitters separately in `ATool/QtPrototype`.

Document Manager combines Assembly Template documents and Package Documents. It
shows package order and missing AT/package entries, association controls,
ordering, conditions, document editing, mapping, model and resolution controls.
Its lower buttons select Properties, Source JSON or Match Details. Properties
includes name, description, package and the constituent clause tree.

Layout Manager follows the selected document and exposes each layout, content,
iterator and field. It supports creation, editing, removal, ordering, copy/paste,
path browsing and condition evaluation. Properties use individual controls;
iteration-scoped field values and trigger details are shown in their context.

Field Manager supports Name and Path views, filtering, editing, Mandatory,
path browsing and mapped values. Blue indicates mapped/triggered/PASS and red
indicates unmapped/untriggered/FAIL. Zero and false remain valid mapped values.
Document and Layout Matched Only defaults activate when data is mapped and allow
inspection of failing items when unchecked.

Clause Manager inspects saved definitions without evaluating them against mapped
data. Document/layout selection supplies the composer target. Library selection
inspects a clause independently. Controls support adding, saving, deleting,
composition, clause-name completion, Help, usage searches, raw-condition searches
and trigger-update review. Usage results navigate to owners; update review supports
Apply Current, Skip and Apply All with changed-source checks and undo.

Data Browser supports JSONPath, full text and condition searches, lazy expansion,
complete value inspection and exact-path copying. Clear restores the mapped tree.

Content Manager supports Comms listing/filtering, versions, metadata, scoped fields,
source/rich HTML, local HTML files and create/save/new-version operations. Its
embedded editor supports Comms data/condition/loop chips, picker/source loop editing,
formatting, original point sizes, table structure and cell/table styles. Unedited
HTML stays exact; Cancel, undo/redo and stale-source protection are supported.

## Menus and workflows

File provides Save, Save As, Open Session, local package storage, About and Exit.
Edit supports undo/redo; tree-local copy/paste/delete shortcuts act on the selected
layout items. Cmd/Ctrl+O opens shared packages, Cmd/Ctrl+S saves and Cmd/Ctrl+M maps;
the original Windows Alt aliases and redo shortcut remain available.

Package provides shared edit/testing copies, owned-session resume, close, retrieval
from Comms, shared update, Comms publication, sync checks, lock release/manual
unlock, Preview, Email and cancellation. Advanced provides local/raw opening and
protected local cleanup. Testing copies cannot be saved to the shared package.

Config supports Set, Lock/Unlock, scheduled Lockouts, Create, List, Close and Migrate,
including original session aliases and close/migration protection. Resources supports
all original categories, single/type/all downloads, recent choices and independent
Download All cancellation. Model supports cached View, Generate and Generate All.
Data provides mapping/remapping, XML conversion, generated editable samples and
cached layout resolution with text/JSON report saves.

Preview supports render types, mapped/file input, effective date, timeout, Pre-Prod,
chart exclusion and configured output openers. Email requires a current Dry Run
before Generate and invalidates that validation when its inputs change.

Settings edits a draft of the original ATool preferences at `~/.atool/.settings.json`.
Cancel leaves active settings and the document view intact. Save validates and
commits the draft; conflicts from external changes are reported. Reopening loads
fresh preferences and retains unknown settings. Comms operations use the configured
CLI, aliases, cache and shared folders.

## Persistence and release files

Local authoring uses one editable model with undo/redo. Save preserves unknown JSON
and creates original-byte backups, checks external changes and writes bundles
transactionally. Shared updates verify locks and baseline hashes, retain five history
snapshots and roll back failed updates. Copies with absolute or external references
become self-contained portable bundles. Publication refreshes files at their original
locations and retains authoring history while preserving refreshed server metadata.

The repository release builder includes both applications, both sets of launchers,
the Qt dependency file, Qt modules and embedded HTML/JavaScript/settings assets.
A worktree release archive was extracted and its executable macOS launcher started in a separate temporary folder;
its sample, managers and packaged build metadata loaded successfully. The release
builder's normal publication remains controlled by GitHub Actions.

## Verification

The full automated suite currently passes 246 tests:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests
```

Four separate checks exercise real Qt WebEngine editor behavior:

```sh
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu .venv/bin/python tests/check_qt_content_editor.py
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu .venv/bin/python tests/check_qt_content_chips.py
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu .venv/bin/python tests/check_qt_content_tables.py
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu .venv/bin/python tests/check_qt_content_formatting.py
```

On macOS, WebEngine checks require native process access. Tests use temporary
settings/files and a local fake CLI; they do not publish to live Comms, send email,
or alter user shared storage. Coverage includes authoring, save/conflict recovery,
manager/menu controls, mapping/diagnostics, shared lifecycle, download/publish/preview/
email contracts, transport cancellation/retries, settings and embedded editing.
Native Windows execution and live Comms operation have not been exercised on this
macOS host. The completed requirement audit is recorded in `atool_qt/parity_completion_audit.json`, with all 217 original button/menu/checkbox call sites reconciled in the control inventory.

Review corrections: editing controls wrap in narrow panels; compact Document and Layout buttons retain the original symbols; Clear filters and the layout folder toggle are restored. The status bar shows package/version, mapped data file and the original lock, edit/view, unsaved and sync indicators, with explanatory tooltips. Startup is empty and no built-in sample package is offered.

Package retrieval uses compact cancellable progress dialogs that close after successful list, version probe and download steps. Failed commands retain their output for inspection. Diagnostic logging goes to Activity instead of the launch terminal; the known Qt accessibility empty-table warning is filtered without disabling other warning categories. The regression flow exercises shared installation with a local fake CLI and temporary storage.

Documents, layouts and fields display ` *` when their source differs from the saved baseline. Markers clear after save or undo; labels never change the stored item names. Fields append ` x2`, ` x3`, etc. for multiple mapped values in both Name and Path views. Clause Manager uses three vertical stacks: library list, clause editor and condition composer. Stack sizes are saved separately from the former column layout.

Dialogs use the operating system window controls instead of duplicate Close buttons. Cancel, Save, Apply and operations such as Close Package or Close Configuration remain available. Window-close cancellation and cleanup are verified by the workflow tests.

Convert and Map opens the XML picker immediately, remembering its own last-used directory and falling back to the mapped-data location. Canceling the initial picker dismisses the dialog. Successful conversion and mapping close the dialog automatically; conversion failures, missing output, changed-package guards and mapping errors keep their status visible.
