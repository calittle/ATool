# ATool Release Notes

This release focuses on mapping visibility, match diagnostics, window startup behavior, and release-package transparency.

## Mapping Results Are Easier To Review

- After mapping a data file, the Documents list now keeps both matched and unmatched documents visible.
- Triggered documents are shown in blue.
- Untriggered documents are shown in red.
- The status bar shows the total document count and how many documents matched.
- A mapped-only filter button appears after mapping:
  - `Show Triggered` filters the Documents list to only triggered blue documents.
  - `Show All` removes that filter and shows all mapped documents again.
  - `Clear Map` hides the filter button and clears mapping colors/details.

## Unmatched Documents Explain Why They Failed

Selecting a red unmatched document now shows a `Match Details` section in Document Details.

The new format is intended to be read top-down:

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

## Map Button Feedback

Clicking `Map` now immediately changes the button to `Opening...` and disables it while the data-file picker is being opened. This gives visible feedback during the short delay before the operating-system file dialog appears.

## Startup And Menu Behavior

On startup, ATool now:

1. Opens the main window.
2. Opens Field Manager.
3. Opens Clause Manager.
4. Returns focus to the main window.

The app menu is now attached to the main window, Field Manager, and Clause Manager so `File`, `Package`, `Data`, `Settings`, and `Window` remain available as focus moves between those windows.

## Release Package Notes

Release zip artifacts now include a generated `NOTES.MD` file. The generated file includes:

- artifact name
- build source (`head` or `worktree`)
- commit SHA
- build timestamp
- a `git show --stat` commit snippet for the packaged commit
- worktree status and diffstat when built with `--source worktree`

This makes the release package self-describing, so users can open `NOTES.MD` from the zip and see what changed without needing repository access.
