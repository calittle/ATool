# ATool Release Notes

## v2.1.1

- Preserve the selected Layout Manager field or iterator and expanded branches
  when editing a Path, instead of briefly switching documents during refresh.
- Restore the exact Document and Field Manager selection after edits and saves,
  independently of held shortcut keys; retain deliberate multiple selections.
- Bundle OCCS CLI v1.2.7, replacing v1.2.6. Document models now flag missing or
  inactive Assembly Template layout/content references with affected paths and
  alternative placements, and correctly identify layouts with configured conditions.

## v2.1.0

- Add a package-specific Favorites Manager. Mark fields and clauses as favorites,
  see their mapped values or PASS/FAIL results together, filter by result, and
  jump back to the original field or clause. Favorites are saved in user settings
  separately for each package.
- Remember the Preview Package Exclude Charts choice across dialogs and app restarts.
- Cache email distribution lists under `~/.atool/email-routes` when no Comms Cache
  Folder is configured, so Send Email does not require refreshing on each use.
- Add Activity & Logs settings for retained Activity history, log location, maximum
  file size and rotated backups. Defaults are a 1 MiB Activity backlog and logs in
  `~/.atool/logs`, with 10 MiB per file and five backups plus the current file.
- Keep Activity responsive with batched updates, bounded history and background
  file writes. Show concise HTTP summaries in Activity and retain full sanitized
  diagnostics in log files when Debug Logging is enabled. Stop retaining duplicate
  HTTP trace records in CLI results, and report queue overflow or file-write errors.
- Add a top-level Activity menu matching the right-click commands: Copy, Select
  All, Open Current Log, Show Log Folder, Save Activity and Clear Activity. Flush
  pending file writes before opening the current log; report write errors or
  timeouts instead of opening stale contents. Clearing Activity preserves saved
  logs and subsequent file diagnostics for operations already running.

## v2.0.5

- Select email distribution routes by name from the Comms cache or refresh them
  from Comms. Send the selected Communication UUID and transaction directly,
  including routes without direct Email template relationships. Remember the
  five most recent Distribution choices per environment.
- Make recipients editable with recent-address suggestions and multiple selection
  where the input format supports it. Make the mapped JSON path readable and
  remove the Send Email dry-run and saved-name steps.
- Show timed operation details and sanitized HTTP requests/responses in Activity
  when Debug Logging is on. Preserve useful address prefixes and domains, routing
  UUIDs, template names and error context while masking credentials and personal
  values. Summarize large configuration lookups and keep trace output separate
  from machine-readable command results.
- Treat Comms business errors and manual-review responses as failures even with
  HTTP 2xx, and report acceptance without claiming inbox delivery.
- Reject malformed condition paths with duplicated root/current markers after a
  dot, including during negation and short-circuit evaluation. Explain the path
  error in validation and condition diagnostics.
- Bundle OCCS CLI v1.2.6, replacing v1.2.5, for distribution-route enumeration,
  explicit Communication routing, business-error handling and sanitized diagnostics.

## v2.0.4

- Replace the default Python icon with a ruby-red glass AT monogram on a
  smoked-black glass tile. Include native Mac and Windows application icons,
  set the running window icon for Qt and legacy launchers, and give Windows
  an ATool taskbar identity.

- Support non-ebill notification emails using
  `sendDetail.deliveryInfo.contactValue`, including input wrapped in
  `CommunicationInfo.CommunicationData`. Override one recipient in temporary
  input while preserving the original mapped JSON and notification fields;
  explain when multiple addresses cannot be used for this format.
- Bundle OCCS CLI v1.2.5, replacing v1.2.4. The CLI now supports recipient
  overrides for `sendDetail` notifications, completing the non-ebill email fix.
- Rename Data Browser to Data Manager and add editing of mapped JSON values,
  properties, arrays and whole branches, with copy/paste and undo/redo. Save to
  the current file or use Save JSON As to make a copy the source for subsequent
  previews and remapping. Refresh mapped fields and document matches after edits.
- Simplify Data Manager labels while retaining full paths in tooltips and Copy
  Path. Use the mapped file's saved location when filenames match another file
  in the working directory, so Preview reads the intended data.
- Fix layout resolver counts for wrapped filtered length expressions so matches
  in nested arrays are counted correctly.
- Resolve fields and nested conditional content inside content conditions using
  the current iteration row. Preserve condition structure when resolved values
  contain quotes or operators, and show unknown fields in the resolution evidence.

## v2.0.3

- Run selected Preview render types as independent jobs in the shared
  four-operation queue. Open each file as soon as its render finishes, retain
  individual and Cancel All Previews cancellation, and keep temporary input
  available until all renders finish.
- Remove redundant render type labels from Preview filenames. Keep metadata
  identifiable and prevent output and diagnostic files from overwriting one another.
- Fix regex matching in document JSONPath triggers, including compound conditions,
  mapping results, validation and diagnostic explanations.
- Give the condition editor more room in Layout Properties.

## v2.0.2

- Allow multiple package previews to share the regular four-operation queue.
  Queue additional previews, keep output files separate, and support individual
  cancellation or Cancel All Previews.
- Include preview execution IDs and available response context in Activity when
  Debug Logging is enabled, including failed, cancelled and timed-out previews.
- Add right-click options to clear Activity or save its contents to a log or
  text file. Clearing during an operation preserves subsequent log messages.
- Save clause-form edits with File → Save so newly added or edited clauses can
  be used immediately. Report empty clause expressions accurately.
- Allow independent application windows while preventing the same package
  from being opened in multiple windows.
- Add Copy Item Name to Resolve Layout and improve native migration and
  bundled CLI setup instructions.

## v2.0.1

- Add Refresh Item beside Expand All in Resolve Layout. Document, Layout and
  Content selections can retrieve the latest cached resource and update the
  resolved tree while retaining the selected item.
- Preserve neighboring cached resources during single-item downloads and keep
  the previous resource when a download fails or is cancelled.
- Provide self-contained native applications for Apple Silicon Mac, Intel Mac
  and Windows, including Python, Qt, Node.js and OCCS CLI.
- Bundle the latest published stable OCCS CLI release in native applications.
  Build and publish releases on version tag pushes; main commits do not build.
- Fix native Windows runtime paths and clause composer autocomplete activation.

## v2.0.0

- The default application is now the unified PySide6/Qt workspace. Documents,
  Layouts, Fields, Clauses, Data Manager and Content Manager are dockable,
  tabbed, detachable panels. Windows and macOS launchers are included, with
  separate legacy launchers retaining the original Tkinter application.
- Integrated package document ordering and associations, editing controls,
  original menus, package/data status and shared-package workflows.
- Added mapped values, iteration details, blue/red trigger diagnostics,
  constituent clause trees and detailed match explanations. Changed items
  display an asterisk; fields with multiple values display their count.
- All grids support column resizing and header-click sorting, with lavender
  row selection and a purple outline. Field Manager supports multi-field
  copy/paste across packages, duplicate naming and undo/redo.
- Layout resolution uses a collapsible evidence grid. Conditional fragments
  accept whitespace, and selectors preserve layout context so included content
  can find its configured iterator. Text and JSON exports remain available.
- Successful Comms operations close their progress windows automatically.
  Mapping and conversion remember their directories; Preview defaults to the
  loaded JSON file. Dialogs stay on screen when the workspace extends past
  a monitor edge.
- Release archives include the Qt application and its HTML/JavaScript assets,
  pinned dependencies and both platforms' launchers.

## v1.1.4

- Package Preview now lets you choose an effective date with a calendar or by
  entering `YYYY-MM-DD`. The selected date is sent to OCCS; it defaults to today
  when ATool starts and stays selected for later previews in the same session.
- Opening a layout field in Data Manager now includes its parent iteration path
  in the search, so fields inside repeated data resolve in the right context.

## v1.1.3

- `File > Open Session` now restores the shared package context for the last
  local copy. It resumes edit mode when the current user still owns its lock,
  or opens the copy in test mode when the lock no longer matches.
- The Layouts window can now copy and paste content, iterations, and fields in
  addition to layouts. Pasted items keep their nested data, and pasted content
  or fields receive unique identities when needed.
- Added `Shift+Cmd/Ctrl+C`, `D`, `L`, and `P` shortcuts for Clause Manager,
  Data Manager, Layouts, and Package Documents, respectively.
- A layout item's Condition button now opens that expression in Data Manager's
  new Condition mode and shows whether it passes against the mapped data.
- Moving a layout item up or down now keeps that item selected and preserves
  the expanded tree state.
- OCCS preview filenames now include the selected environment (`non` or `pre`)
  and a readable timestamp.

## v1.1.2

- Assembly Template documents without a package association are highlighted in
  the Documents list, with a tooltip explaining their status. Package Documents
  can now associate an existing document by matching its short name in the
  Comms document catalog, then publish the association through the package
  workflow.
- `Shift+Cmd/Ctrl+F` opens Field Manager, including when focus is in a search
  field.
- Up to four regular OCCS operations can run concurrently. Operations that
  write to the same Config cannot overlap, and simultaneous login retries for
  the same session are coordinated.
- Confirmation and information dialogs now use consistent, width-aware ATool
  windows that remain centered over their parent.
- Release publishing now queues runs for the same tag so concurrent attempts
  do not create competing GitHub Releases.

## v1.1.1

- The main heading is now **ATool for OCCS**, and the window title now shows
  the open package and version rather than the assembly-template filename.
- The bottom-left status panel now shows shared-lock ownership (`🔒`/`🔓`),
  access (`✏️` edit or `👁` test/view), and change indicators (`🟡` unsaved AT,
  `⬆️` unpublished package associations), plus package sync state: `➡️` for a
  local copy that needs updating to shared storage and `☁️` for a shared package
  that needs publishing. Its tooltip describes only the current indicators.
- Closing, releasing a shared edit lock, quitting, or opening another package
  now requires an acknowledgement when the active edit copy differs from shared
  storage, including edits made directly in package files.
- Publishing to Comms is now an action from a locked shared edit session; it
  retains that edit lock and no longer creates a separate publish mode.
- Test packages cannot be saved. Local-package, raw-AT, and local-cleanup
  actions are now grouped under `Package > Advanced`.
- Layout and document editing now provide a direct Resolve action, more compact
  controls, and context-aware layout actions.
- Field Manager now supports one-step undo and redo for field edits. Empty
  computed numeric mappings display as `0`.
- Native alerts, prompts, file pickers, and custom ATool dialogs now center
  over the window that opened them.

## v1.0.8

- Added `Data > Resolve...` to inspect how a cached document layout resolves against mapped data, including nested layouts, conditions, selected and suppressed content, and mapped fields.
- Added effective-date and `PackagePageNum` controls, cached root-layout choices, text and JSON evidence export, and a companion resolver CLI.
- Added a unified browser Content Editor and updated launchers and package dependencies to support it.

## Earlier Changes

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

- Added ATool-only Config lifecycle protection stored in the shared package
  folder's `config-lockouts.json`. `Config > Lock` toggles the active Config's
  protection, while the Config list exposes lock/unlock actions and a 🔒 lock
  indicator for protected configurations.
- Added `Config > Lockouts...` for shared time-based close/migration lockouts.
  Users select a date, 24-hour time, IANA timezone, and duration; the dialog
  previews local start/end times and renders expired windows in grey.
- Close and migration reread Config locks and lockout windows before running
  (and migration checks again after session refresh), blocking protected work.
- Config selection and lifecycle UI now show Config names rather than internal
  Config IDs/UUIDs.
- Added `Config > Create...`, which creates an open Config ID through `occs create-config` using the configured OCCS session and request timeout.
- Added `Config > List`, which shows the open Config IDs returned by `occs list-configs` for the configured OCCS session and lets the user close a selected Config ID.
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
- `Package > Close Package` now closes the currently open package, prompts to save dirty changes first, and prompts shared edit sessions to update the shared package before closing.
- `Package > Clean Local Packages...` now supports multi-select toggling, keeps keyboard focus in the package list after spacebar toggles, and refreshes an open cleanup window when the current package is closed.
- `Get to Shared/Edit` now respects existing shared package locks: the lock owner can update the shared package from Comms, while other users must use `Get to Local` or manually unlock after confirming the lock is stale.
- Checkout and save flows no longer offer to replace another user's shared package lock; manual unlock is now the explicit override path.
- `Package > Get Packages from Comms...` now replaces the separate list/get Comms menu items with one list-first workflow.
- The Package menu now groups preview/cancel, open/close and local cleanup actions, Comms retrieval, shared publish/update, and lock actions separately.
- The Comms package list hides internal ID/UUID columns, supports local filtering, and lets users choose `Get to Local` or `Get to Shared/Edit`.
- After selecting a Comms package, ATool now loads available package versions, sorts them newest/highest first, and preselects the top version before download.
- Package menu shortcuts were added for Preview (`Cmd/Ctrl+P`), Update Shared Package (`Cmd/Ctrl+U`), and Publish Package to Comms (`Shift+Cmd/Ctrl+U`).
- `File > Open Session` now reopens the last package and remaps the last JSON data file with `Shift+Cmd/Ctrl+O`.
- Comms/OCCS requests now show a running elapsed timer in a dedicated status-bar operation segment, such as `⏱️ 2s Previewing...`, without hiding the open file/package summary.

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

`File -> About ATool` now identifies a build by its exact release tag when available, otherwise by its git commit ID, and shows the support contact (`andy.little@oracle.com`). Dirty worktree builds add `-dirty`.

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
