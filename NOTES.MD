# ATool Release Notes

This release focuses on shared package edit flow, Comms publish behavior, Comms authentication resilience, document/layout editing ergonomics, mapping review, conversion workflow, preview ergonomics, macOS window readability, menu cleanup, Comms-compatible condition handling, and release-package transparency.

## Comms Authentication

- Comms package/config commands now auto-run `occs login` and retry once when OCCS returns a plain HTTP 401 response such as `401 Unauthorized` or `401 Authorization Required`.
- User Settings now include an OCCS session alias so ATool can consistently run package, preview, conversion, and config-list commands against the intended saved session such as `np`.

## Shared Package Editing And Comms Publish

- Opening a shared package version no longer asks whether to check Comms for a newer copy before opening.
- If you already hold the edit lock for a shared package version, opening it now offers to resume the existing local edit session instead of reacquiring the lock and creating a fresh local copy.
- Local edit locks now remember the active local edit folder so iterative local saves can be resumed before updating the shared package.
- Publishing a shared package to Comms now publishes directly from the shared `published/current` folder instead of creating a temporary local publish copy first.
- The Comms publish dialog labels the package source as `Shared Folder` when it is publishing from the shared package folder.
- `Package > Get Packages from Comms...` now replaces the separate list/get Comms menu items with one list-first workflow.
- The Comms package list hides internal ID/UUID columns, supports local filtering, and lets users choose `Get to Local` or `Get to Shared/Edit`.
- After selecting a Comms package, ATool now loads available package versions, sorts them newest/highest first, and preselects the top version before download.
- Package menu shortcuts were added for Preview (`Cmd/Ctrl+P`), Update Shared Package (`Cmd/Ctrl+U`), and Publish Package to Comms (`Shift+Cmd/Ctrl+U`).
- Comms/OCCS requests now show a running elapsed timer in the status bar, such as `[2s] Previewing package clp_bills...`.

## Documents And Layouts Panels

- The Documents panel now has a `+Document` button for adding documents directly.
- Document movement supports multi-select in flat view.
- Document movement adds `Top`, `Bottom`, and `Auto Move` controls.
- `Auto Move` places selected documents near similarly named documents.
- Repeated document movement clicks now work without moving the mouse off and back onto the button.
- The Layouts panel now places `+Layout` to the left of `+Content`.
- Layout controls now use shorter labels: `+Content`, `Up`, `Down`, `+Iteration`, and `+Field`.
- Layouts now opens in its own window, is available from `Window > Show Layouts`, and remembers its window size and position.
- The document toolbar `Sample` button was removed; sample input generation is now available from `Data > Generate Sample...`.

## Document Details Panel

- `Triggered` is hidden until data has been mapped.
- `Updated` now appears directly under Description.
- Parent and Children display rows were removed.
- Condition and Match Details are collapsible, and the collapsed state is saved across app sessions.
- When either Condition or Match Details is collapsed, the still-open section expands to use the available details-panel space.
- Match Details now appears under Condition in Document Details instead of in a separate resizable panel.
- Match Details now shows a simplified clause list: passing clauses are blue, failing clauses are red, and hovering a clause shows the matched values or failure reason.
- The condition ellipsis button was removed because selecting a document already populates Clause Manager.

## Mapping Results Are Easier To Review

- After mapping a data file, the Documents list now starts in `Show Triggered` mode so matched documents are visible immediately.
- Use `Show All` to inspect the full mapped document list, including failed matches.
- Triggered documents are shown in blue.
- Untriggered documents are shown in red.
- The status bar shows the total document count and how many documents matched.
- The short-lived `Mapping: ...` text was removed from the lower status bar.
- `Clear Map` clears mapping colors/details and hides the mapped-result filter.

## Unmatched Documents Explain Why They Failed

Selecting a red unmatched document shows a `Match Details` section in Document Details.

The diagnostics are intended to be read top-down:

```text
Overall: FAIL
Logic: AND - all 5 clauses must pass.

Failed clauses:
- Tariff_E-NRT_is
  Check: @..billCalcHdrList[?(@.rateSched == 'E-NRT')] empty false
  Expected: @..billCalcHdrList[?(@.rateSched == 'E-NRT')] should be present and non-empty.
  Found: parent path missing: $..billCalcHdrList.

Passed clauses:
- Manual_Bill_isNot
- ENGLISH_is
```

Useful interpretation rules:

- `Overall: FAIL` means the document did not trigger for the mapped data file.
- `Logic: AND` means every listed clause must pass.
- `Logic: OR` means at least one listed clause must pass.
- `Expected` describes what the condition required.
- `Found` describes what the mapped data actually produced.
- `empty false` means the path was expected to find at least one value.
- `Found: no values.` means that path did not match anything in the mapped data.

## Convert And Map Workflow

- The Data menu now includes `Convert and Map...`.
- This converts an XML bill file to JSON, then maps the generated JSON to the open assembly template automatically.
- Convert and Map now has a keyboard shortcut: `Shift+Cmd+M` on macOS and `Shift+Ctrl+M` on Windows/Linux.
- The workflow reuses the existing conversion validation, including multi-Bill-ID confirmation and overwrite prompts.
- If conversion succeeds but the generated JSON cannot be found, ATool reports the conversion output path instead of silently failing.

## Preview Workflow And Package Menu

- `Preview...` is now the final item in the Package menu, separated from package management commands by a divider.
- The Preview dialog now focuses the `Preview` button by default, so pressing Enter starts the preview.
- When preview output is opened automatically, ATool no longer shows an extra completion popup first.
- Preview still reports output paths when automatic opening is disabled or no output file is available to open.

## macOS Window Readability

- ATool now applies explicit light backgrounds and selection colors on macOS.
- Main windows, managers, dialogs, popups, and tooltips use the same styled toplevel creation path.
- Text boxes, list boxes, tree views, entries, and combo boxes are styled to avoid dark-mode readability issues.

## Comms-Style Size Conditions Now Map Correctly

ATool now recognizes top-level `size` checks in document conditions, matching Comms behavior for expressions such as:

```text
@.billPrint.premise.premList[*].serviceAgreement.saList[*].billSegment.bsegList[*].billCalcHdr.billCalcHdrList[*].billCalcLine.billCalcLineList[?(@.cmElements.chargeType == 'EC')].cmElements.chargeType size 1
```

This fixes cases where Comms triggered a document but ATool showed a failed clause because it treated `size 1` like part of the JSONPath. The mapping diagnostics now report the resolved value count, matched values, and expected size.

## Map Button Feedback

Clicking `Map` now immediately changes the button to `Opening...` and disables it while the data-file picker is being opened. This gives visible feedback during the short delay before the operating-system file dialog appears.

## Startup And Menu Behavior

On startup, ATool now:

1. Opens the main window.
2. Opens Field Manager.
3. Opens Clause Manager.
4. Returns focus to the main window.

The app menu is attached to the main window, Field Manager, and Clause Manager so `File`, `Package`, `Data`, `Settings`, and `Window` remain available as focus moves between those windows.

`File -> About ATool` now shows the app build number and support contact (`andy.little@oracle.com`). Packaged builds use the git commit recorded in `BUILD_INFO.txt` as the build number source, dirty worktree builds add `-dirty`, and local development runs fall back to the current short git hash.

## Release Package Notes

Release zip artifacts include a generated `NOTES.MD` file. The generated file includes:

- artifact name
- build source (`head` or `worktree`)
- commit SHA
- dirty worktree status
- build timestamp
- a `git show --stat` commit snippet for the packaged commit
- worktree status and diffstat when built with `--source worktree`

This makes the release package self-describing, so users can open `NOTES.MD` from the zip and see what changed without needing repository access.
