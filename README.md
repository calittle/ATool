# ATool User Guide

> ## UNSUPPORTED — NOT AN ORACLE PRODUCT
>
> This is an independent open-source utility. It is not an Oracle product and
> is not supported, endorsed, maintained, or warranted by Oracle. Use it at
> your own risk; obtain support for Oracle products through Oracle's official
> support channels.
>
> ATool is licensed under the [GNU General Public License, version 3](LICENSE).

ATool (Assembly Template Tool) is a cross-platform Python desktop app for working with Oracle Communications Cloud Service (OCCS) Packages and Assembly Templates.

Version 2.0.2 uses a unified Qt workspace with dockable, tabbed, detachable panels
for Documents, Layouts, Fields, Clauses, Data and Content. The original Tkinter
application remains available through the legacy launchers.

## Native application downloads

GitHub Actions builds three native ZIPs for version releases:

| Download | Computer | Launch |
| --- | --- | --- |
| `ATool-macos-arm64.zip` | Apple Silicon Mac | `ATool.app` |
| `ATool-macos-x86_64.zip` | Intel Mac | `ATool.app` |
| `ATool-windows-x86_64.zip` | 64-bit Windows | `ATool/ATool.exe` |

Get the ZIP matching your computer from
[GitHub Releases](https://github.com/calittle/ATool/releases).
Extract the ZIP, then double-click the application. On macOS you can move
`ATool.app` to Applications; on Windows keep `ATool.exe` with its `_internal`
folder.

Use **File → New Window** (**Cmd+N** on macOS, **Ctrl+N** on Windows) to open
another independent copy of ATool. Each window can open its own package and map
its own data, and closing one leaves the others running.
Each package can be open in only one ATool window on your computer, including
local copies, testing copies and other versions of that package. Close the
package in its current window before opening it in another.

These downloads include Python, Qt/PySide6, Qt WebEngine, Node.js, OCCS CLI and
its npm dependencies. No Python/Node installation, virtual environment,
dependency installation, or terminal launcher is needed. Configure your OCCS
connection and credentials in ATool after launching. Existing settings and
sessions remain in your user profile. An explicitly configured CLI path still
overrides the bundled CLI; clear that setting to use the included version.

The native apps are not currently Developer ID signed/notarized on macOS or
Authenticode signed on Windows. Standard operating-system trust checks may
apply to downloaded builds. SHA-256 checksum files accompany the ZIPs.

### Using the bundled OCCS CLI directly

You can run OCCS CLI from a native ATool download without installing a separate
Node.js or OCCS CLI. The bundle includes the CLI's JavaScript dependencies.
Some optional CLI commands also need external programs, which you install
separately:

| External tool | Required for |
| --- | --- |
| Graphviz (`dot`) | Generating SVG graphs with `graph` |
| Poppler (`pdftoppm`, `pdfinfo`) | PDF smoke-test thumbnails, page counts, and rasterizing PDF pages for visual comparisons |
| ImageMagick (`identify`, `compare`) | Visual comparisons of PDF or HTML outputs in two-tenancy smoke tests |
| Chrome or Chromium | HTML smoke-test thumbnails and HTML visual comparisons |

Follow the [OCCS CLI prerequisite installation instructions](https://github.com/calittle/OCCS-CLI#prerequisites)
for your operating system. When using ATool's bundled CLI, skip the separate
Node.js/npm installation and the CLI's `npm install`/`npm link` steps; those
runtime dependencies are already included. Install only the external tools
needed by your commands. Add the
folders containing the Graphviz, Poppler and ImageMagick executables to the
terminal's `PATH`. The CLI invokes the names listed above directly; an
ImageMagick installation providing only `magick` does not provide the
`identify` and `compare` commands it expects. Verify the tools you installed:

```text
dot -V
pdftoppm -v
pdfinfo -v
identify -version
compare -version
```

The CLI checks common Chrome/Chromium installation locations. For a browser in
another location, set `OCCS_SMOKE_BROWSER` to its executable's full path, as in
the examples below. ATool's embedded Qt WebEngine includes Chromium for the
editor, but does not supply the standalone browser executable these CLI
commands need.

**macOS — Terminal**

Set this up once if you want to run OCCS CLI commands directly, for example to
generate graphs, run smoke tests or automate work outside ATool's interface.
Using ATool's normal buttons and menus does not require this setup.

The setup gives you an `occs` command in every new Terminal window. It runs
ATool's bundled CLI with its bundled Node.js, so you do not need a separate
CLI or Node.js installation.

1. Open the **Terminal** app. For the standard macOS zsh shell, enter:

   ```bash
   nano ~/.zshrc
   ```

   This opens your shell startup file, creating it if it does not exist.
2. Add the following at the end of that file, below any existing settings.
   Adjust the first path if ATool is installed somewhere other than Applications.
   These lines belong in `~/.zshrc`, not in an ATool file:

   ```bash
   ATOOL_RUNTIME="/Applications/ATool.app/Contents/Frameworks/runtime"
   occs() {
     "$ATOOL_RUNTIME/node/node" "$ATOOL_RUNTIME/occs-cli/bin/occs.js" "$@"
   }
   ```

3. If the CLI needs an explicit browser location for HTML smoke tests, add this
   line to the **same file**, using the path to your installed browser:

   ```bash
   export OCCS_SMOKE_BROWSER="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
   ```

4. In nano, press **Control+O**, then **Return** to save, and **Control+X** to exit.
   Open a new Terminal window and run `occs --help` to check the setup.

You only edit `~/.zshrc` once. From then on, enter `occs` commands in Terminal.
Work from a writable folder so generated files are saved outside the application.
For example, run the following **in Terminal**, not in `~/.zshrc`:

```bash
mkdir -p "$HOME/Documents/occs-cli-work"
cd "$HOME/Documents/occs-cli-work"
occs graph --help
occs smoke --help
```

**Windows — PowerShell**

For direct CLI use on Windows, save the command in your PowerShell profile once.
PowerShell loads this file when you open a new window, making `occs` available
without repeating the setup. ATool's normal buttons and menus do not need it.

For external PDF and comparison tools, follow the
[Poppler installation steps](https://github.com/calittle/OCCS-CLI#poppler-on-windows)
and [ImageMagick installation steps](https://github.com/calittle/OCCS-CLI#imagemagick-on-windows).
Poppler's executables are in its extracted `Library\bin` folder. ImageMagick
must provide `identify.exe` and `compare.exe`; enable its legacy utilities
option if offered. The instructions include user `PATH` setup and verification
commands. Open a new PowerShell window after changing `PATH`.

1. Open **PowerShell** and run these commands to open your profile in Notepad,
   creating it if necessary:

   ```powershell
   New-Item -ItemType Directory -Force (Split-Path -Parent $PROFILE) | Out-Null
   if (!(Test-Path -LiteralPath $PROFILE)) {
     New-Item -ItemType File -Path $PROFILE | Out-Null
   }
   notepad $PROFILE
   ```

2. Add the following to the end of the profile file. Replace the example path
   with the extracted folder containing `ATool.exe`:

   ```powershell
   $AToolRuntime = "C:\path\to\ATool\_internal\runtime"
   function occs {
     & "$AToolRuntime\node\node.exe" "$AToolRuntime\occs-cli\bin\occs.js" @args
   }
   ```

3. If the CLI needs an explicit browser location, add this to the **same profile
   file**, using your browser's executable path:

   ```powershell
   $env:OCCS_SMOKE_BROWSER = "C:\Program Files\Google\Chrome\Application\chrome.exe"
   ```

4. Save the file and close Notepad. Open a new window in the same PowerShell
   application and run `occs --help`. Windows PowerShell and PowerShell 7 have
   separate profiles; configure the one you intend to use.

Run your commands from a writable working folder. Enter the following **in
PowerShell**, not in the profile file:

```powershell
New-Item -ItemType Directory -Force "$HOME\Documents\occs-cli-work" | Out-Null
Set-Location "$HOME\Documents\occs-cli-work"
occs graph --help
occs smoke --help
```

Both setups persist across terminal sessions. If you move ATool, update its
runtime path in the startup/profile file. If you want to keep an existing
standalone `occs` command as well, name the function `atool-occs` instead and use
that name for the bundled CLI.

Use `occs graph --help`, `occs smoke --help`, and `occs login --help` for command
options. CLI sessions are stored in your user profile; use a saved session or
log in through the CLI for commands accessing OCCS. See the
[OCCS CLI user guide](https://github.com/calittle/OCCS-CLI#readme) for cache,
graph and smoke-suite setup.

Installing these tools enables the corresponding CLI commands; it does not add
graph or smoke-test controls to ATool's interface. Run the bundled CLI using
the bundled Node.js shown above, and keep the application's runtime files
together. Each ATool download retains its own bundled CLI version.

## Moving an older ATool installation to the native app

Users of ATool 1.x or source-based 2.0.0 can move to the 2.0.2 native download
without setting up Python, a `.venv`, Node.js or a separate OCCS CLI. Existing
native-app users can use the same steps to replace an older native download.

1. Save your work and close ATool. Back up your packages, templates, input files,
   and user settings. Check for working files saved inside the old application
   or standalone CLI folder, including smoke suites, `.env` files and outputs.
2. Extract the native ZIP for your computer into a new location. Launch
   `ATool.app` on macOS or `ATool.exe` on Windows. Keep the old installation until
   you have verified the new one. Native downloads use these executables;
   source-download scripts such as `Run_ATool.command` and `Run_ATool.bat` still
   require their Python environment.
3. In **Settings → User Settings**, clear **CLI Path** and save to use the
   bundled OCCS CLI. An existing custom path overrides the bundle, even after
   upgrading. Keep a custom path only if you deliberately want a standalone CLI.
4. Verify your local package, shared storage, Comms cache and model folder paths.
   If any are inside the old installation folder, keep that folder or move the
   working files and update the settings before removing it. Remap input files
   if their saved locations change.
5. Reopen a package or session, map your input, and verify the operations you
   normally use, such as a resource download and Preview. Existing user-profile
   settings and saved CLI sessions are reused; log in again if the session has
   expired. Update desktop shortcuts, Dock/taskbar pins and scripts to launch
   the new native application.

### Optional cleanup after migration

| Old component | What to do |
| --- | --- |
| The old source installation's `.venv` | Remove it after validating the native app if you no longer need to run the old source or legacy interface. Native ATool does not use it. |
| An old source or native application folder | Remove it once you have moved or preserved any working files and updated shortcuts and configured paths. |
| A standalone OCCS CLI folder or global `occs` command | Keep it if other scripts, terminal commands or users need it. It can coexist with the bundled CLI. Remove it only after checking those dependencies and clearing ATool's custom CLI path. |
| System Python or Node.js | Native ATool does not need these installations, but other software may. Removing them is not required for migration. |
| Graphviz, Poppler, ImageMagick, Chrome/Chromium | Keep them if you use the bundled or standalone CLI's graph or smoke-test features. |

Keep the user-profile `.atool` directory and all configured package, cache,
model and shared-storage folders. Also retain `.occs-session.json` and the
`.occs-cli` directory in your user profile: the latter contains the key used
to read saved CLI credentials. On macOS the user profile is your home folder;
on Windows it is `%USERPROFILE%`. These are user data, not disposable
application runtime files. ATool does not automatically delete old installations.

## Requirements for running from source

- Python 3.10–3.15 (required by the pinned PySide6 version)
- PySide6 (installed from `requirements.txt`)
- OCCS CLI access for OCCS package, preview, mapping, and conversion actions
- `tkinter` is needed only for the original application

**Qt is not included with standard Python.** ATool 1.x users may never have
installed it. Installing `requirements.txt` installs PySide6 (the Python Qt
bindings) and its Qt runtime automatically. You do not need to install the Qt
SDK or Qt Creator separately. Dependency installation requires internet access.

## Installation from source

Download the ATool application ZIP from the **Assets** section of the
[2.0.2 release](https://github.com/calittle/ATool/releases/tag/v2.0.2) and extract
it to a folder where you can write files. Keep the extracted files together.
If upgrading from 1.x, read [Upgrading from 1.x](#upgrading-from-1x) below first.

### macOS

1. Check that Python is version 3.10–3.15:

   ```bash
   python3 --version
   ```

2. If Python is missing or outside that range, install a supported version from
   [python.org](https://www.python.org/downloads/macos/). Reopen Terminal and
   check the version again.
3. Create ATool's environment and install its dependencies. Replace the example
   folder path with the folder you extracted:

   ```bash
   cd "/path/to/ATool"
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```
4. Verify PySide6 is available to ATool:

   ```bash
   .venv/bin/python -c "import PySide6; print(PySide6.__version__)"
   ```

   This should print `6.12.0`. Double-click `Run_ATool.command` to start ATool.

### Windows

1. In PowerShell, check that Python is version 3.10–3.15:

   ```powershell
   py -3 --version
   ```

2. If Python is missing or outside that range, install a supported version from
   [python.org](https://www.python.org/downloads/windows/). Enable
   **Add python.exe to PATH** and the Python launcher during installation.
   Reopen PowerShell and check the version again.
3. Create ATool's environment and install its dependencies. Replace the example
   folder path with the folder you extracted:

   ```powershell
   cd "C:\path\to\ATool"
   py -3 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
4. Verify PySide6 is available to ATool:

   ```powershell
   .venv\Scripts\python.exe -c "import PySide6; print(PySide6.__version__)"
   ```

   This should print `6.12.0`. Double-click `Run_ATool.bat` to start ATool.

If you have several Python versions installed, use the supported version
explicitly when creating the environment: for example, `python3.13 -m venv
.venv` on macOS or `py -3.13 -m venv .venv` on Windows, if Python 3.13 is installed.

## Upgrading from 1.x

For the native app, follow
[Moving an older ATool installation to the native app](#moving-an-older-atool-installation-to-the-native-app)
above. The steps below apply to the **source distribution**. Its main change
is the unified Qt workspace: copying source files alone is not enough; install
the updated dependencies before launching. The default source launchers now
start the Qt application.

1. Save your work and close ATool 1.x.
2. Keep your existing ATool folder as a fallback. Back up your packages and
   user settings, including any custom storage locations. Settings normally
   live in `~/.atool` on macOS or `%USERPROFILE%\.atool` on Windows. The default
   local package folder is `occs-bundles` inside that directory; shared storage
   may be elsewhere, such as OneDrive.
3. Download and extract the 2.0.2 application ZIP into a **separate folder**.
   Follow the macOS or Windows installation steps above in that new folder.
   Create a fresh `.venv`; do not copy the old environment into the new folder.
   This also handles 1.x installations that used an older Python version.
4. Launch using the **new folder's** `Run_ATool.command` (macOS) or
   `Run_ATool.bat` (Windows). Update shortcuts that still point to the old folder
   or directly to `ATool.py`.
5. Open **Settings → User Settings** and verify your OCCS CLI and storage paths.
   The existing `.atool/.settings.json` settings file is reused, including
   configured local, shared, cache and model folders. Keep those folders in
   place. If moving the application changes the location of your OCCS CLI,
   update its path here; the CLI is not installed by `requirements.txt`.
6. Use **File → Open Session** to reopen your previous package and mapped JSON
   file when their saved paths still exist. On first use, this can read the
   original application's saved bundle session. Alternatively, use
   **Package → Open Shared Package…** or open your existing template through
   the File menu. If the old data file has moved, map it again from its new location.

You do not need to download packages again or recreate your shared storage
just to upgrade ATool. Do not delete `.atool` during the upgrade. The Qt panel
layout is saved separately; the old application's window positions are not
imported.

### Updating an existing environment instead

If you replace the application files in an existing folder and its `.venv`
already uses Python 3.10–3.15, install the **new** requirements in that folder:

macOS:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Windows:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the PySide6 verification command from the installation section afterward.
If the environment uses an older Python, use the separate-folder installation
above with a supported Python version.

### Returning to the original interface

The 2.0 distribution also includes `Run_ATool_Legacy.command` for macOS and
`Run_ATool_Legacy.bat` for Windows. These start the original Tkinter interface
using the same installed environment. Tkinter must be available for those
launchers; it is not required for the Qt workspace.

## Run ATool

Complete the installation steps above before using a launcher.

### Windows

Double-click:

- `Run_ATool.bat`

Or run from PowerShell:

```powershell
.\Run_ATool.bat
```

### macOS

From Terminal:

```bash
cd /path/to/ATool
zsh Run_ATool.zsh
```

Optional one-time setup if you want to run it as an executable script:

```bash
chmod +x Run_ATool.zsh
./Run_ATool.zsh
```

For a Finder double-click launch, use the included `Run_ATool.command`.
The release ZIP preserves its executable permissions.

### Direct Python Command

If the launchers are unavailable, run the app directly from the ATool folder:

macOS:

```bash
.venv/bin/python ATool_Qt.py
```

Windows:

```powershell
.venv\Scripts\python.exe ATool_Qt.py
```

### Original Application

Use `Run_ATool_Legacy.command` on macOS or `Run_ATool_Legacy.bat` on Windows
to launch the original Tkinter application. Its source remains `ATool.py`.
The Tkinter troubleshooting below applies to that legacy application.

### Workspace Controls

Drag panel titles to dock, tab, detach or rearrange the managers. Use
**View → Panels** to show hidden panels and **View → Reset Layout** to restore
the default arrangement. Clause Manager, Data Manager and Favorites Manager
initially share tabs with Field Manager.

Use the **Favorite** checkboxes in Field Manager and Clause Manager to build a
personal transaction summary in **Favorites Manager**. Favorites are saved by
package name in your local `~/.atool/.settings.json`, without changing package
metadata. The default **Pass / Mapped** filter shows passing clauses and fields
with values. **Fail / Unmapped** shows failing clauses and fields without values;
**All** shows every favorite, including clause errors. Empty strings, nulls and
empty containers count as unmapped; zero and false are values. Before mapping,
all favorite names show “No data loaded.” Click a favorite to open its field or
clause in the corresponding manager. Favorites for missing items are ignored.

Every grid supports column resizing and header-click sorting. Selected rows use
a lavender background and purple outline; PASS/mapped values are blue and
FAIL/unmapped values are red. An asterisk marks changed items. Field Manager
supports multi-field copy/paste with Cmd/Ctrl+C and Cmd/Ctrl+V.

Expanded containers in Data Manager show child property names and array indices
without repeating the parent path. Standalone search results show compact paths
with ancestor context when needed to distinguish matches. The full path remains
above the grid, on hover, and in Copy Path.

Double-click a simple value in the Data Manager's **Value** column to edit it
in place for values up to 50 characters. Text needs no surrounding quotes;
numbers and booleans keep their types. Press Enter to apply or Escape to cancel.
Longer values, objects, and arrays open the JSON editor on double-click.
Compact icons with tooltips provide **Add…** and
**Remove** for mapped JSON. Select an object to add a named property or an array
to append an item; enter JSON values, objects (`{}`), or arrays (`[]`). **Copy**
and **Paste…** (Cmd/Ctrl+C and Cmd/Ctrl+V while the tree is focused) copy whole
branches as JSON and insert them into the selected object or array. Object
pastes ask for a new property name and never overwrite an existing property.
Edits refresh mapped fields and document matches and report the result in Activity.
**Save** (Cmd/Ctrl+S while the tree is focused) writes to the current data file;
if there is no current file, it opens Save As. **Undo** and **Redo** restore
data changes; mapping another file clears this history. **Save JSON As…** saves
the current data to a JSON file and makes that file the mapped data source for
subsequent previews and remapping. The displayed data filename updates to match.
Editing leaves the original input file unchanged
until you use Save or explicitly save over it; save a copy before mapping another file or
closing the app to keep your changes. These controls apply to the native Qt app.

### Generate previews in multiple languages

In **Settings → User Settings → Language**, set **Language mapping** to the
input JSON field that controls print language. It defaults to
`$.billPrint.billDetails.cmElements.billLanguagePreference`. Use an absolute
path with property names and array indices, such as `$.bills[0].language`;
wildcards, filters, and recursive searches are not supported here.

The **Language display mapping** table supports Add and Remove, with these defaults:

| Label | Data | Short Name |
| --- | --- | --- |
| English | ENGLISH | EN |
| Chinese | CHINESE | ZF |

**Package → Preview…** shows a checkbox for each configured language. The
language matching the selected input file is checked and marked with `*`.
Select one or more languages to generate each selected render type in those
languages. Alternate languages use temporary input copies with the mapped
field changed to the configured **Data** value; the source file stays unchanged.
Output filenames include only the language's **Short Name**, for example
`data-Bill-non-2026-10-24_10-30-00-ZF-a1b2c3d4.pdf`.

Data values and Short Names must be unique; Short Names ignore case and allow
letters, numbers, underscores, and hyphens, starting with a letter or number.
If the input language is missing or unrecognized, Preview explains the issue
and leaves all languages unchecked. Leaving them unchecked previews the input
unchanged. Selecting a language requires the mapped field to exist and contain text.

The Layout Resolver displays a collapsible evidence tree with resolved values,
condition results and iteration rows. Expand or collapse branches to inspect
selected content; text reports and JSON evidence can still be saved.

## Troubleshooting Startup

### Python Command Not Found

Install Python from [python.org](https://www.python.org/downloads/), then reopen
Terminal or PowerShell and try again.

### PySide6 Missing or Dependency Installation Fails

`ModuleNotFoundError: No module named 'PySide6'` means the Python environment
running ATool does not have Qt installed. Run the dependency installation and
PySide6 verification commands above using **the `.venv` in your ATool folder**,
then use the provided launcher. Installing PySide6 into a different Python
environment will not fix the launcher.

If installation reports that no matching PySide6 distribution exists, check
the environment's Python version (`.venv/bin/python --version` on macOS or
`.venv\Scripts\python.exe --version` on Windows). It must be 3.10–3.15. Updating
Python on your computer does not change an existing `.venv`; create a new
environment with the supported interpreter as described above. Also check
the installation output for network or proxy errors.

### `tkinter` Missing

If ATool fails on startup with an error like:

- `ModuleNotFoundError: No module named '_tkinter'`
- `No module named tkinter`

Use the steps below.

### macOS

1. Confirm your active interpreter:
   ```bash
   which python3
   python3 --version
   ```
2. If you installed Python from Homebrew and `tkinter` is missing, install Tcl/Tk and relink Python:
   ```bash
   brew install python-tk
   ```
   If `python-tk` is unavailable in your Brew setup, install Python directly from
   [python.org](https://www.python.org/downloads/macos/).

### Windows

1. Re-run the official Python installer from [python.org](https://www.python.org/downloads/windows/).
2. Choose **Modify** your installed version.
3. Ensure **tcl/tk and IDLE** is selected.

### Linux (if applicable)

Install Tk package for your distro.

Examples:

```bash
# Debian/Ubuntu
sudo apt-get install python3-tk

# RHEL/CentOS/Fedora
sudo dnf install python3-tkinter
```

## Core Workflow

1. Open the authoritative shared package workflow:
   - `Package -> Open Shared Package...`
   - `Package -> Get Packages from Comms...`
   - macOS: `Cmd+O`
   - Windows/Linux: `Alt+O`
2. Review and edit:
   - Documents (main window)
   - Fields (separate Fields window)
   - Layouts/properties (main window right side)
3. Save changes:
   - `File -> Save`
   - macOS: `Cmd+S`
   - Windows/Linux: `Alt+S`
4. Optional mapping run:
   - `Data -> Map...`
   - macOS: `Cmd+M`
   - Windows/Linux: `Alt+M`

### Package Access And Publishing

Comms and the shared package workspace are the authoritative package sources.
ATool may create local working copies for edit and test sessions, but these are
implementation storage rather than a normal package source.

The bottom-left status panel consolidates lock ownership, access, and change
state:

- `🔒 ✏️`: you hold the shared package lock and can edit it.
- `🔓 ✏️`: a local package is editable but has no shared lock.
- `🔓 👁`: a test/view session. You can preview, map, and test, but
  cannot save changes.
- `🟡`: unsaved AT changes.
- `⬆️`: unpublished package-association changes.
- `➡️`: the local edit copy differs from shared storage; update the shared
  package first.
- `☁️`: the shared package differs from its recorded Comms baseline; publish it
  to Comms.
- `➡️☁️`: update shared storage, then publish to Comms.

The mode tooltip describes only the indicators currently shown.
Before closing, releasing a lock, quitting, or switching packages, ATool warns
when the active edit copy differs from shared storage. This includes direct file
edits that ATool did not make itself.

## Undo And Redo

`Edit -> Undo` (`Cmd+Z` on macOS; `Ctrl+Z` elsewhere) and `Redo`
(`Shift+Cmd+Z` / `Ctrl+Shift+Z`) provide one-step, instant undo for field edits,
field additions, and field removals. Undo operates only on the affected Fields
list; it does not reload the package from disk.

Use `Package -> Publish Package to Comms...` only from a shared `edit` session.
Publishing pushes that edited package to Comms and retains the edit lock. It is
an action, not a separate package mode.

Rare recovery and maintenance actions remain available under `Package ->
Advanced`: `Open Local Package...`, `Open Raw AT...`, and `Clean Local
Packages...`.

## Config Locks And Lockouts

ATool can protect configurations from being closed or migrated. This protection
is enforced by ATool only; OCCS CLI and Comms do not interpret it.

- Use `Config -> Lock` to lock the active configuration. The same command
  unlocks it after confirmation.
- In `Config -> List`, the Lock column shows a 🔒 for locked configurations;
  select one and use **Lock Configuration** or **Unlock Configuration** to
  change its state.
- Use `Config -> Lockouts...` to add or remove time-based lockout windows.
  A window has a calendar-selected date, 24-hour start time, IANA timezone,
  and duration. The dialog shows calculated start and end times in the local
  timezone; expired windows are grey.

During an active window, ATool blocks every Config close and migration. A
configuration lock blocks close and migration for that named configuration.
Before either operation runs, ATool rereads the shared lock record so another
user's synchronized change is respected.

The record is `config-lockouts.json` in the configured Shared Package Folder.
It contains internal OCCS identifiers for matching only; ATool displays Config
names in the UI. Shared-folder sync safeguards apply when creating, changing,
or removing a lock or lockout.

## What ATool Persists

ATool stores app/user metadata under:

- `~/.atool/`

Per-package metadata is saved as:

- `~/.atool/.<package_slug>.meta.json`

Example:

- `~/.atool/.clp_bills.meta.json`

Important keys:

- `clause_library`: shared reusable clauses for that package
- field true-path cache and other package metadata

## Clause Manager

Open from:

- `Window -> Show Clause Manager`
- Or click the `...` button beside a Document/Layout condition

### Composer Syntax

- `+` or `AND` = logical AND
- `OR`, `||`, or `|` = logical OR
- `(...)` = grouping
- `RAW{...}` = raw condition fragment
- `CLAUSE{clause name}` = explicit reference to clause names containing spaces/special chars

### Embedded Clauses

A clause expression can reference other clauses:

```json
{
  "name": "master_clause",
  "expression": "CLAUSE{sub clause 1} && CLAUSE{sub-clause-2}"
}
```

ATool resolves these recursively when composing/applying conditions.

Cycle detection is enabled (for example `A -> B -> A` is rejected).

## Condition Editing Behavior

- Clause Manager auto-loads the selected target condition.
- It attempts to auto-compose raw logic back into known clause names.
- Unmatched parts are kept as `RAW{...}` fragments.
- Applying composed output writes valid raw OCCS condition (`$[?(...)]`) to the selected target.

### Updating Document Triggers From a Clause

- Edit the clause expression, then click `Update Triggers...`.
- ATool saves the clause and scans document triggers for the old clause expansion.
- Matching documents are shown in a review queue with current/proposed trigger text.
- Use `Apply This` or `Skip` to review iteratively.
- Use `Apply All` to apply every pending exact, embedded, and dependent-clause proposal.
- If a document condition changed after the preview was built, bulk apply skips it for review.

## Best Practices for Clause Management

1. Keep clauses atomic where possible.
2. Use consistent naming.
   - Suggested pattern: `<subject>_<verb>_<suffix>`
   - Examples:
     - `billInfo_has`
     - `STAFF_isNot`
     - `Tariff_E-PLT_is`
3. Use `is` / `isNot` pairs for complements.
4. Use embedded clauses (`CLAUSE{...}`) for readable master logic.
5. Avoid very broad `$..` deep-search paths unless intentional.
6. Keep complex one-offs in `RAW{...}` only when reuse is unlikely.
7. Validate mapped behavior using `Data -> Map...` with representative data files.

## Mutual Exclusion Guidance

OCCS does not enforce mutual exclusivity automatically. If only one document should trigger, define explicit precedence/exclusion rules in conditions, for example:

- `Scenario_B = base_B && !Scenario_A`

In ATool terms, that means composing lower-priority document conditions with explicit `isNot`/negated gate clauses referencing higher-priority logic.

## Sharing Clause Libraries Across Users

ATool stores reusable clauses in package metadata (`clause_library`). Teams can share this safely.

### Recommended Team Model

1. Nominate one package metadata file as source of truth (per package).
2. Share only the `clause_library` section (or the full package meta if coordinated).
3. Version-control exported metadata in a team repo.
4. Review clause-name and logic changes via pull request.

### Simple Share Procedure

1. User A updates clauses in ATool and saves.
2. User A sends:
   - `~/.atool/.<package_slug>.meta.json`
3. User B backs up existing file.
4. User B replaces file and reopens AT in ATool.

### Safer Merge Procedure (Preferred)

Instead of replacing the full metadata file, merge only:

- `clause_library`
- `clause_library_updated_at` (optional)

This avoids overwriting local cache/preferences from other users.

## Save / Backup Behavior

On save, ATool:

1. Writes a timestamped backup file.
2. Overwrites the active AT file.
3. Updates package metadata in `~/.atool/`.
4. Shows a temporary status-bar message (no save success popup).

## Troubleshooting

### Invalid JSON on Open

- ATool attempts auto-correction for common trailing comma issues.
- Corrected file is saved with timestamped `_corrected_...` name.
- Open the corrected file and continue.

### Composer Token Errors

- If clause names include spaces/special chars, use `CLAUSE{exact name}`.
- For ad hoc fragments, use `RAW{...}`.

### Mapping Appears Slow

- Mapping runs in the background.
- Check status bar (`Mapping: Running/Idle`).
- Optional debug logging can be enabled in user settings.
- User Settings can route XML conversion through a selected local XSD instead of the OCCS XML conversion API. Enable **Use local XSD for XML conversion** and choose the XSD file; the setting is used by both Convert XML and Convert and Map.

## Inspect a Cached Layout Resolution

With a package open, a data file mapped, and a document selected, choose
`Data -> Resolve...`. The dialog uses the configured Comms Cache Directory from
User Settings, or you can browse to another cache. Choose an effective date,
set `PackagePageNum` and `GRIDPAGENUMBER` (both default to `1`), and pick one of
the cached document's root layouts. Click **Resolve** to see the selected and
suppressed content and mapped field values. **Save...** exports the text trace
or JSON evidence.

Each click of **Resolve** captures the current open Assembly Template and mapped
data, including unsaved field and document condition edits made while the dialog
is open. The resolver combines that snapshot with active document and content
versions from the cache for the effective date. Edits made during a run take
effect on the next click of **Resolve**. It does not change Comms or the mapped data.

The same resolver can be run without the UI for automation:

```bash
python3 tools/resolve_layout.py \
  --cache /path/to/comms-cache \
  --package CLP_bills \
  --document BULK_BILL \
  --layout 'header: address' \
  --data /path/to/bill.json \
  --effective-date 2026-09-25
```

`PackagePageNum` and `GRIDPAGENUMBER` default to `1`. Override them with
`--system-field PackagePageNum=2` and `--system-field GRIDPAGENUMBER=2`. Use
`--format json` for a structured evidence tree, and
`--output /path/to/report.txt` to save the result. If the cache has multiple
Assembly Template versions, select one with `--at-version`.

This pass supports direct data fields, `concat` and `length` field paths,
conditional text/content includes, package-wide Assembly Template conditions
for non-always layout/content relationships, iterator paths and their row fields,
`empty false`/`not empty` conditions, and Comms' one-based `substring` transform.
It marks unsupported transforms, unknown fields, unresolved iterator markers,
and cached relationships with missing or conflicting Assembly Template
conditions in the report. The text is a content facsimile; page layout, fonts,
and barcode drawing still require a Comms render.
## JSONPath preflight

The **User Settings → Comms → Check length() JSONPaths (experimental)** option
is **off by default** while PD's restriction is being clarified. When enabled,
saving an AT, updating a shared package, and publishing to Comms check for
`length()` used with relative paths (`@.items`, `items`) or recursive searches
(`$..items`, `$.root..items`). Both `path.length()` and `$.length(path)` forms
are checked in field/iteration Paths, Conditions, and saved clause expressions.
Use an explicit absolute path without recursive descent, and verify that it
counts the intended nodes. Normal `@` predicates within an absolute path's
filter remain allowed, for example `$.items[?(@.active == true)].length()`.

In installed releases, use **Package → Audit JSONPaths…** to review the open
template, including unsaved edits and the current clause library. The report
shows owner names, JSON locations, and expressions, with Copy Report and Save
Report controls. This manual audit works even with automatic preflight off and
in read-only package sessions. Findings are review candidates while PD's
restriction is being clarified.

From a source checkout, you can also audit files without opening them:

```sh
python3 tools/audit_jsonpath_length.py /path/to/assembly-template.json --output /tmp/length-audit.json
```

The audit also accepts multiple files, bundle directories, or bundle manifests.
This explicit command always runs the audit, independently of User Settings.
It reports each affected expression with its JSON location and owner names.
Exit status is 0 for a clean audit, 1 for findings, and 2 for unreadable inputs.
