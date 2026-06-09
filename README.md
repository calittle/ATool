# ATool User Guide

ATool (Assembly Template Tool) is a cross-platform Python desktop app for working with Oracle Communications Cloud Service (OCCS) Assembly Template (AT) JSON files.

## Requirements

- Python 3.10+ (recommended)
- `tkinter` (bundled with standard Python installers on macOS/Windows)
- OCCS CLI access for OCCS package, preview, mapping, and conversion actions

ATool currently uses only Python standard library modules. There is no `pip install`
or virtual environment setup required for normal users.

## Internal Distribution

For internal use, share the ATool folder or a zip containing:

- `ATool.py`
- `Run_ATool.bat`
- `Run_ATool.zsh`
- `README.md`
- `NOTES.MD`

Do not include local cache or generated folders such as `.venv`, `__pycache__`,
or user-specific files under `~/.atool/`.

## Automated Build Artifact

This repo includes a local post-commit build hook. When enabled, each commit
builds a zip artifact from the committed `HEAD` snapshot and writes it to:

- `dist/ATool-<timestamp>-<commit>.zip`

If a local SharePoint/OneDrive sync folder is configured, the same artifact is
also copied there, along with a stable `ATool-latest.zip` file.

Each release zip includes a generated `NOTES.MD` file with commit details and a
short change summary for the packaged snapshot.

### Enable the Git Hook

Run this once from the repo root:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/post-commit tools/build_artifact.py
```

### Configure the SharePoint Destination

Use either an environment variable:

```bash
export ATOOL_ARTIFACT_DIR="/path/to/local/SharePoint/folder"
```

Or create a local, ignored `.atool-build.local.json` file:

```json
{
  "sharepoint_dir": "/path/to/local/SharePoint/folder"
}
```

The checked-in `.atool-build.local.json.example` shows the expected shape.

### Build Manually

Build from the latest committed snapshot:

```bash
python3 tools/build_artifact.py --source head
```

Build from the current working tree:

```bash
python3 tools/build_artifact.py --source worktree
```

## Install Python

### macOS

1. Check if Python exists:
   ```bash
   python3 --version
   ```
2. If not installed, install from:
   - [python.org](https://www.python.org/downloads/macos/)
3. Verify:
   ```bash
   python3 --version
   ```

### Windows

1. Check if Python exists:
   ```powershell
   py --version
   ```
2. If not installed, install from:
   - [python.org](https://www.python.org/downloads/windows/)
3. During install, enable **Add python.exe to PATH**.
4. Verify:
   ```powershell
   py --version
   ```

## Run ATool

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

If you want a Finder double-click launcher on macOS, rename or copy the script as
`Run_ATool.command`, then run `chmod +x Run_ATool.command`.

### Direct Python Command

If the launchers are unavailable, run the app directly from the ATool folder:

macOS:

```bash
python3 ATool.py
```

Windows:

```powershell
py -3 ATool.py
```

## Troubleshooting Startup

### Python Command Not Found

Install Python from [python.org](https://www.python.org/downloads/), then reopen
Terminal or PowerShell and try again.

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

1. Open an OCCS package, local package, or raw assembly template:
   - `Package -> Open Shared Package...`
   - `Package -> Open Local Package...`
   - `Package -> Open Raw AT...`
   - `Package -> List Packages from Comms...`
   - `Package -> Get Package from Comms...`
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
- Use `Apply All Exact` for whole-trigger matches that use only the changed clause.
- Embedded and dependent-clause matches remain in the queue for explicit review.

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
