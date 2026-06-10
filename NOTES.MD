# ATool Release Notes

This release focuses on shared package edit flow, Comms publish behavior, document/layout editing ergonomics, mapping review, conversion workflow, preview ergonomics, macOS window readability, menu cleanup, Comms-compatible condition handling, and release-package transparency.

## Shared Package Editing And Comms Publish

- Opening a shared package version no longer asks whether to check Comms for a newer copy before opening.
- If you already hold the edit lock for a shared package version, opening it now offers to resume the existing local edit session instead of reacquiring the lock and creating a fresh local copy.
- Local edit locks now remember the active local edit folder so iterative local saves can be resumed before updating the shared package.
- Publishing a shared package to Comms now publishes directly from the shared `published/current` folder instead of creating a temporary local publish copy first.
- The Comms publish dialog labels the package source as `Shared Folder` when it is publishing from the shared package folder.

## Documents And Layouts Panels

- The Documents panel now has a `+Document` button for adding documents directly.
- Document movement supports multi-select in flat view.
- Document movement adds `Top`, `Bottom`, and `Auto Move` controls.
- `Auto Move` places selected documents near similarly named documents.
- Repeated document movement clicks now work without moving the mouse off and back onto the button.
- The Layouts panel now places `+Layout` to the left of `+Content`.
- Layout controls now use shorter labels: `+Content`, `Up`, `Down`, `+Iteration`, and `+Field`.

## Document Details Panel

- `Triggered` is hidden until data has been mapped.
- `Updated` now appears directly under Description.
- Parent and Children display rows were removed.
- Condition and Match Details are collapsible, and the collapsed state is saved across app sessions.
- Match Details now appears under Condition in Document Details instead of in a separate resizable panel.
- The condition ellipsis button was removed because selecting a document already populates Clause Manager.

## Mapping Results Are Easier To Review

- After mapping a data file, the Documents list now starts in `Show Triggered` mode so matched documents are visible immediately.
- Use `Show All` to inspect the full mapped document list, including failed matches.
- Triggered documents are shown in blue.
- Untriggered documents are shown in red.
- The status bar shows the total document count and how many documents matched.
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
- The workflow reuses the existing conversion validation, including multi-Bill-ID confirmation and overwrite prompts.
- If conversion succeeds but the generated JSON cannot be found, ATool reports the conversion output path instead of silently failing.

## Preview Workflow And Package Menu

- `Preview...` is now the final item in the Package menu, separated from package management commands by a divider.
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

## Release Package Notes

Release zip artifacts include a generated `NOTES.MD` file. The generated file includes:

- artifact name
- build source (`head` or `worktree`)
- commit SHA
- build timestamp
- a `git show --stat` commit snippet for the packaged commit
- worktree status and diffstat when built with `--source worktree`

This makes the release package self-describing, so users can open `NOTES.MD` from the zip and see what changed without needing repository access.
