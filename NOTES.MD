# ATool Release Notes

This release focuses on shared package edit flow, Comms publish behavior, Comms authentication resilience, document/layout editing ergonomics, mapping review, conversion workflow, preview ergonomics, macOS window readability, menu cleanup, Comms-compatible condition handling, and release-package transparency.

## Comms Authentication

- Comms package/config commands now auto-run `occs login` and retry once when OCCS returns a plain HTTP 401 response such as `401 Unauthorized` or `401 Authorization Required`.
- User Settings now include an OCCS session alias so ATool can consistently run package, preview, conversion, and config-list commands against the intended saved session such as `np`.
- Document trigger mapping now treats multi-value equality comparisons the same way Comms metadata does, preventing broad wildcard paths such as service agreement type lists from triggering extra documents in ATool.
- Long-running OCCS CLI operations can now be canceled from `Package > Cancel OCCS Operation` or Cmd/Ctrl+., including package previews with long timeouts.

## User Settings

- User Settings now include `Confirm on Quit`, enabled by default. When enabled, ATool asks for confirmation before quitting from Cmd+Q, File > Exit, or the window close control.
- User Settings now include an OCCS `Config ID Filter` regular expression. When set, the Publish Package to Comms Config ID dropdown only shows matching Config IDs, names, or labels.
- User Settings now include Config Source and Target session aliases, defaulting to `np` and `pp`, for Config close and migration commands.
- User Settings now include a default OCCS request timeout in seconds (360 by default), used for package, config, conversion, and automatic-login operations.

## Config Management

- Added `Config > Get Resource to Cache`, which refreshes the selected Package, Style, Layout, Content, Font, or Document cache from Comms into the Comms Cache Folder configured in User Settings. The dialog remembers the five most recently requested name/type pairs.
- Added `Config > Close...`, which loads open Config IDs from the configured source session, applies the Config ID Filter, and runs `occs close-config --session <source> --config-id <config>`.
- After a Config closes successfully, ATool now asks whether to run migration immediately.
- Added `Config > Migrate`, which runs `occs migrate --source-session <source> --target-session <target>`.

## Layout Mapping Diagnostics

- The Layouts panel now colors every item with a mapped path or condition: blue when the data satisfies it, red when it does not. Layout Properties also show PASS/FAIL status for condition evaluation and mapping status in Summary, while mapped iterations and fields continue to show their current mapped values under Mapped.
- Iterated layout fields now require every iterator row to map a value before they are colored blue; missing values in any row leave the field red.

## Shared Package Editing And Comms Publish

- Opening a shared package version no longer asks whether to check Comms for a newer copy before opening.
- If you already hold the edit lock for a shared package version, opening it now offers to resume the existing local edit session instead of reacquiring the lock and creating a fresh local copy.
- Local edit locks now remember the active local edit folder so iterative local saves can be resumed before updating the shared package.
- Publishing a shared package to Comms now publishes directly from the shared `published/current` folder instead of creating a temporary local publish copy first.
- The Comms publish dialog labels the package source as `Shared Folder` when it is publishing from the shared package folder.
- The Comms publish Config ID picker now hides closed Config IDs before applying the optional Config ID filter.
- Publishing to Comms now aborts when open Config IDs cannot be loaded or none match the configured filter, and the Config ID picker only accepts IDs returned by Comms.
- Publishing to Comms from an editable shared package no longer leaves the open package stranded in publish mode; if that state already exists, Save now moves the in-memory changes into a local edit copy and locks it for editing.
- Publishing to Comms now works after updating the shared package while keeping the edit lock; ATool refreshes the lock baseline and skips the redundant shared-update prompt when local and shared package contents already match.
- Shared package edit locks now refresh their baseline hashes when the lock owner updates or publishes the shared package, preventing stale owned locks from blocking later saves.
- `Package > Manual Unlock Shared Package...` now lets users release a stale shared package lock after selecting the locked package version and confirming the unlock.
- `File > Close Package` now closes the currently open package, prompts to save dirty changes first, and prompts shared edit sessions to update the shared package before closing.
- `File > Clean Local Packages...` now supports multi-select toggling, keeps keyboard focus in the package list after spacebar toggles, and refreshes an open cleanup window when the current package is closed.
- `Get to Shared/Edit` now respects existing shared package locks: the lock owner can update the shared package from Comms, while other users must use `Get to Local` or manually unlock after confirming the lock is stale.
- Checkout and save flows no longer offer to replace another user's shared package lock; manual unlock is now the explicit override path.
- `Package > Get Packages from Comms...` now replaces the separate list/get Comms menu items with one list-first workflow.
- The Package menu now groups preview/cancel, open actions, Comms retrieval, shared publish/update, and lock actions separately, while local package cleanup has moved to the File menu.
- The Comms package list hides internal ID/UUID columns, supports local filtering, and lets users choose `Get to Local` or `Get to Shared/Edit`.
- After selecting a Comms package, ATool now loads available package versions, sorts them newest/highest first, and preselects the top version before download.
- Package menu shortcuts were added for Preview (`Cmd/Ctrl+P`), Update Shared Package (`Cmd/Ctrl+U`), and Publish Package to Comms (`Shift+Cmd/Ctrl+U`).
- `File > Open Session` now reopens the last package and remaps the last JSON data file with `Shift+Cmd/Ctrl+O`.
- Comms/OCCS requests now show a running elapsed timer in a dedicated status-bar operation segment, such as `[2s] Previewing package clp_bills...`, without hiding the open file/package summary.

## Documents And Layouts Panels

- Cmd/Ctrl+F now focuses the search field in the main Documents panel, Field Manager, and Clause Manager.
- Field Manager names now append one asterisk per mapped value when a field maps multiple values, such as `DC41**` for two values.
- Field Manager now shows a Remove Field button only when a field is selected, confirms removal, and removes the field from the assembly template.
- Adding a field now clears the Field Manager search and mapped-only filters, selects the new field, and moves keyboard focus to it.
- Field Manager hides Collapse All and Expand All outside Path view.
- The Documents panel now has a `+Document` button for adding documents directly.
- The Documents panel now has a `-Document` button that confirms before removing the selected document and its child documents from the assembly template.
- Document movement supports multi-select in flat view.
- Document movement adds `Top`, `Bottom`, and `Auto Move` controls.
- `Auto Move` places selected documents near similarly named documents.
- Repeated document movement clicks now work without moving the mouse off and back onto the button.
- The Layouts panel now places `+Layout` to the left of `+Content`.
- Layout controls now use shorter labels: `+Content`, `Up`, `Down`, `+Iteration`, and `+Field`.
- Layouts now opens in its own window, is available from `Window > Show Layouts`, and remembers its window size and position.
- Layouts can now be copied and pasted between documents with Cmd/Ctrl+C and Cmd/Ctrl+V, including multi-selected layouts and their nested contents.
- The Layouts toolbar is more compact and now includes an Expand/Collapse toggle for the full layout tree.
- The document toolbar `Sample` button was removed; sample input generation is now available from `Data > Generate Sample...`.

## Package Documents

- Added `Window > Show Package Documents Manager` for managing package document associations alongside the Assembly Template document list.
- The Package Documents manager shows package association order, associated state, and diagnostics for AT-only or association-only documents.
- Package document columns are filterable and sortable, with order shown first and sorted in package order by default.
- Selecting a Package Documents row now selects the matching AT document in the main Documents tree when one exists.
- Associated documents can be reordered from the Package Documents manager; this updates `DocumentRelIndex` in the package version metadata.
- The main Documents panel now follows that package document order; its redundant document move controls were removed.
- Associated documents can toggle `Always trigger`; this updates `DocumentAlwaysTriggerInd`.
- AT document trigger conditions can be edited from Package Documents. Empty conditions are allowed, but non-empty conditions must use the Comms AT wrapper format such as `$[?(...)]`; malformed delimiters or obvious non-AT expressions are blocked before writing the AT JSON.
- Adding from the document catalog creates the package association and, when missing, creates a minimal AT document shell with `$$Id`, `Updated`, `Descr`, `Condition`, and empty `Layouts`.
- Removing a package association leaves the AT document and its details intact.
- The document catalog is cached at `~/.atool/document-catalog.json` and can be refreshed from Comms directly from the add dialog.
- Package association edits mark local package metadata as changed. The main window title uses `*` for unsaved AT JSON edits and `!` for unpublished package association changes; the status bar also shows `Local package changes`.
- Publishing to Comms now parses OCCS `SFD0375` lock errors and offers to retry with the Config ID that already owns the package lock.

## Document Details Panel

- `Triggered` is hidden until data has been mapped.
- `Updated` now appears directly under Description.
- Parent and Children display rows were removed.
- Condition and Match Details are collapsible, and the collapsed state is saved across app sessions.
- When either Condition or Match Details is collapsed, the still-open section expands to use the available details-panel space.
- Match Details now appears under Condition in Document Details instead of in a separate resizable panel.
- Match Details now shows a simplified clause list: passing clauses are blue, failing clauses are red, and hovering a clause shows the matched values or failure reason.
- Match Details now preserves composed `AND` / `OR` grouping so related scenario clauses are shown under their parent logic instead of as a flat ambiguous list.
- The condition ellipsis button was removed because selecting a document already populates Clause Manager.

## Mapping Results Are Easier To Review

- After mapping a data file, the Documents list now starts in `Show Triggered` mode so matched documents are visible immediately.
- `Data > Remap` reloads the currently mapped JSON file from disk after clearing the existing map, and is also available with `Alt+Cmd/Ctrl+M` or Shift-click on `Clear Map`.
- Use `Show All` to inspect the full mapped document list, including failed matches.
- Triggered documents are shown in blue.
- Untriggered documents are shown in red.
- Field Manager now colors mapped fields blue and unmapped fields red after mapping, and includes a `Show Mapped` / `Show All` toggle while mapped data is active.
- The status bar shows the total document count and how many documents matched.
- The status bar now keeps file/package, operation timing, mapped data file, mapping state, document count, and field count visible as separate segments.
- `Clear Map` clears mapping colors, field values, document Match Details, and hides the mapped-result filter.
- New fields added while a data file is mapped now default to a placeholder path such as `$.NewField1` instead of `$`, preventing the Mapped Value panel from filling with the entire JSON payload.
- Count mappings that wrap filtered JSONPaths, such as `$.length($..billCalcLineList[?(@.cmElements.chargeType == 'FCC')].cmElements).length())`, now ignore trailing wrapper parentheses so the mapped field shows the matched count instead of no value.
- Cached count-mapping true paths also trim stale trailing wrapper parentheses when a package is reopened, preventing old metadata from preserving a broken mapped count.
- ATool now strips embedded line breaks from package text values entered in editable fields and from existing package text values on load, preventing newline characters in assembly-template strings from breaking Comms.

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
- If a condition operand such as `@.MyEnergyChargeCount` matches an ATool field name but is absent from the input JSON, Match Details now explains that Comms conditions do not resolve ATool field aliases and suggests using the field's JSON path instead.

## Convert And Map Workflow

- The Data menu now includes `Convert and Map...`.
- This converts an XML bill file to JSON, then maps the generated JSON to the open assembly template automatically.
- Convert and Map now has a keyboard shortcut: `Shift+Cmd+M` on macOS and `Shift+Ctrl+M` on Windows/Linux.
- The workflow reuses the existing conversion validation, including multi-Bill-ID confirmation and overwrite prompts.
- If conversion succeeds but the generated JSON cannot be found, ATool reports the conversion output path instead of silently failing.
- Windows subprocess output is now decoded as UTF-8 with replacement fallback, preventing Convert and Map from crashing when OCCS emits bytes that do not decode under the Windows `cp1252` console code page.

## Preview Workflow And Package Menu

- `Preview...` is now the final item in the Package menu, separated from package management commands by a divider.
- The Preview dialog now focuses the `Preview` button by default, so pressing Enter starts the preview.
- The Preview dialog now remembers the last submitted render type selection and timeout.
- Preview timeout values are no longer capped at 180 seconds, allowing longer OCCS renders to be configured and reused.
- When preview output is opened automatically, ATool no longer shows an extra completion popup first.
- Preview still reports output paths when automatic opening is disabled or no output file is available to open.

## macOS Window Readability

- ATool now applies explicit light backgrounds and selection colors on macOS.
- Main windows, managers, dialogs, popups, and tooltips use the same styled toplevel creation path.
- Text boxes, list boxes, tree views, entries, and combo boxes are styled to avoid dark-mode readability issues.
- Browse/Open/Save native file dialogs launched from child dialogs now attach to the main ATool window and restore focus to the child dialog afterward, avoiding window jostling on macOS.

## Comms-Style Size Conditions Now Map Correctly

ATool now recognizes top-level `size` checks in document conditions, matching Comms behavior for expressions such as:

```text
@.billPrint.premise.premList[*].serviceAgreement.saList[*].billSegment.bsegList[*].billCalcHdr.billCalcHdrList[*].billCalcLine.billCalcLineList[?(@.cmElements.chargeType == 'EC')].cmElements.chargeType size 1
```

This fixes cases where Comms triggered a document but ATool showed a failed clause because it treated `size 1` like part of the JSONPath. The mapping diagnostics now report the resolved value count, matched values, and expected size.

Filtered empty checks now treat a missing filtered parent path as empty in Comms-compatible evaluation, matching the local condition result to the intended empty-filter behavior.

Missing scalar leaf checks now match OCCS more closely: a missing leaf path such as `@.developerAccount empty true` no longer passes locally. Use a parent-object filter such as `@.cmElements[?(@.developerAccount == 'Y')] empty true` when a condition needs to pass for missing non-developer flags.

Comms-compatible `!=` comparisons now treat a missing path as not equal to a present literal value. For example, `@.billPrint.billDetails.cmElements.billTag != 'Adjusted Bill'` now passes when `billTag` is absent, matching Comms document-trigger behavior.

Single-quoted filter literals that look like function calls, such as `@.cmElements.unitIndicator == '(min)'`, now remain visible as Comms-compatibility warnings but no longer force the local condition check to fail when ATool can evaluate the path.

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
