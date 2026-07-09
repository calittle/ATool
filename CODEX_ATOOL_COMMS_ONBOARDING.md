# Codex Onboarding: ATool And Comms

Use this file to give a new Codex setup enough project context to work on ATool
and to reason about Comms/OCCS package behavior. It is written as a handoff for
another engineer or analyst who already has access to the ATool repo, OCCS CLI,
and any customer package/data files they are allowed to use.

## Copy/Paste Prompt For Codex

Paste this at the start of a new Codex thread:

```text
You are working in the ATool repo.

ATool is a Python/Tk desktop tool for Oracle Communications Cloud Service
(OCCS/Comms) packages and Assembly Templates. Read README.md, NOTES.MD, and this
onboarding file before making assumptions. The app is mostly one large file,
ATool.py, with launchers Run_ATool.zsh and Run_ATool.bat. Normal users do not
need pip dependencies; it uses the Python standard library plus tkinter.

Important working rules:
- Do not change code unless I explicitly ask for code changes.
- If I ask why a document did or did not trigger, inspect the assembly-template
  JSON and the mapped input JSON read-only, then explain the exact condition
  gates that pass/fail.
- Treat Comms/OCCS document conditions as JSONPath-like expressions wrapped as
  $[?(...)].
- Remember that ATool fields/aliases do not exist to Comms document triggers;
  triggers evaluate against the input JSON payload.
- When comparing ATool local mapping to Comms, prefer Comms-compatible behavior:
  missing filtered parents can count as empty for empty checks, missing scalar
  leaves are not always the same thing, and missing paths can satisfy != literal
  checks.
- Package associations and document order are separate from AT document entries.
  A document can exist in the AT but not be associated with the package, and an
  association can exist while the AT shell is missing or minimal.
- Always protect user data: do not overwrite assembly templates, package metadata,
  local package folders, or ~/.atool files unless asked.

Useful local files:
- README.md: user guide and core workflow.
- NOTES.MD: current behavior and release notes.
- BUILD.md: build/package guidance.
- ATool.py: implementation.

Useful user-data locations:
- ~/.atool/: ATool app metadata, package metadata, local/shared package cache,
  document catalog, and edit-lock state.
- ~/.atool/.<package_slug>.meta.json: per-package metadata, including
  clause_library and field true-path cache.
- ~/.atool/occs-bundles/.../assembly-template.json: package bundle AT files
  downloaded or edited locally.

Common task pattern:
1. Read the exact files the user names.
2. Locate the relevant document by $$Id in assembly-template.json.
3. Extract its Condition string.
4. Break the condition into gates: language, tariff/rate schedule, scenario,
   bill tag, multiple contract, manual/copy/final/FIT/HVSDR/etc.
5. Compare each gate against the input JSON at exact paths.
6. Report the first hard blocker and any later blockers or confirming matches.
7. Mention if the document is missing from the AT or only present in package
   associations.
```

## Mental Model

ATool helps users inspect and edit Comms/OCCS packages, especially
`assembly-template.json`. In Comms terms, the assembly template is where document
definitions, layout/content trees, iterations, fields, and conditions live.
ATool adds a UI around that JSON plus package metadata, clause libraries,
mapping diagnostics, preview, conversion, and Comms package/config operations.

The core distinction:

- **Assembly Template document**: an entry under `Documents` in
  `assembly-template.json`, keyed by `$$Id`, with a `Condition` and `Layouts`.
- **Package document association**: package metadata saying which documents are
  associated with the package, their order, and whether they always trigger.
- **Input data**: the JSON payload mapped or previewed against the template.
- **Fields**: reusable template field definitions. They can be useful in layouts,
  but Comms document trigger conditions evaluate against the input JSON, not
  against ATool field aliases.

When a document does not render, it may be because its AT condition fails, because
it is not associated with the package, because package order/always-trigger state
differs from the AT, or because the wrong local/shared package copy is being used.

## Repo Basics

Main files:

- `ATool.py`: the desktop app implementation.
- `README.md`: installation, run workflow, clause manager, mapping, save behavior.
- `NOTES.MD`: recent features and behavior changes.
- `BUILD.md`: packaging guidance.
- `Run_ATool.zsh`: macOS launcher.
- `Run_ATool.bat`: Windows launcher.
- `tools/build_artifact.py`: release zip builder.

Run locally:

```bash
python3 ATool.py
```

or:

```bash
zsh Run_ATool.zsh
```

Normal users should not need `pip install`.

### macOS Python Selection

When running ATool itself or importing `ATool.py` for helper/evaluator snippets
on macOS, first find a Python that satisfies both requirements:

- Python 3.10+ syntax support.
- `tkinter` import support.

Do not assume `/usr/bin/python3` or the first `python3` on `PATH` is correct.
On this machine, `/usr/bin/python3` has Tk but is too old for ATool's Python
3.10+ type syntax, while `/opt/homebrew/bin/python3` may be new enough but can
miss `_tkinter`. Check candidates directly:

```bash
which -a python3
python3.12 - <<'PY'
import sys
print(sys.version)
import tkinter
print("tk ok")
PY
```

If `python3.12` is available and prints `tk ok`, prefer it for local checks:

```bash
python3.12 ATool.py
python3.12 -m py_compile ATool.py
```

For read-only JSON inspection that does not import ATool, any working Python 3
is fine.

## ATool Data Locations

ATool stores user and package data under:

```text
~/.atool/
```

Important examples:

```text
~/.atool/.clp_bills.meta.json
~/.atool/document-catalog.json
~/.atool/occs-bundles/<package-version-folder>/assembly-template.json
```

Per-package metadata may contain:

- `clause_library`: reusable named clauses.
- field true-path cache.
- package metadata and local mapping cache.

Do not casually overwrite these files. They are user-specific and may represent
active work.

## Comms/OCCS Workflows In ATool

ATool can use OCCS CLI for package and render operations. User-facing workflows
include:

- `Package -> Get Packages from Comms...`
- `Package -> Open Shared Package...`
- `Package -> Open Local Package...`
- `Package -> Open Raw AT...`
- `Package -> Preview...`
- `Data -> Convert and Map...`
- `Config -> Close...`
- `Config -> Migrate`

User settings include OCCS session aliases so package, preview, conversion,
config close, and migration commands run against the intended Comms environment.

## Trigger Debugging Workflow

When asked "why did/didn't document X trigger?", do this:

1. Open the attached `assembly-template.json`.
2. Find the document object where `$$Id` equals the requested document.
3. Copy the `Condition` exactly.
4. Open the input JSON and inspect only the relevant paths.
5. Break the condition into readable gates.
6. Identify which gates pass and which gates fail.
7. If a named document is absent from the AT, say that explicitly.
8. If a likely sibling/counterpart exists, mention it as an inference.

Good facts to check first:

- `$.billPrint.billDetails.cmElements.billLanguagePreference`
- `$.billPrint.billDetails.cmElements.multipleContractAccount`
- `$.billPrint.billDetails.cmElements.billTag`
- `$.billPrint.billDetails.cmElements.consumptionRemarks`
- `$.billPrint.billDetails.cmElements.billChars`
- `$.billPrint.premise.premList[*].serviceAgreement.saList[*].saType`
- `$.billPrint.premise.premList[*].serviceAgreement.saList[*].cmElements.saChars`
- `$.billPrint.premise.premList[*].serviceAgreement.saList[*].billSegment.bsegList[*].billCalcHdr.billCalcHdrList[*].rateSched`
- `$.billPrint.premise.premList[*].serviceAgreement.saList[*].billSegment.bsegList[*].billCalcHdr.billCalcHdrList[*].billCalcLine.billCalcLineList[*].cmElements.chargeType`
- `$.billPrint.premise.premList[*].serviceAgreement.saList[*].billSegment.bsegList[*].billCalcHdr.billCalcHdrList[*].billCalcLine.billCalcLineList[*].cmElements.unitIndicator`
- `$.billPrint.premise.premList[*].serviceAgreement.saList[*].billSegment.bsegList[*].bsegSQ.bsegSQList[*].sqi`

Common gate meanings:

- `billLanguagePreference == 'ENGLISH'`: English document family.
- `billLanguagePreference == 'CHINESE'`: Chinese document family.
- `multipleContractAccount == true`: multiple-contract family.
- `multipleContractAccount empty true`: single-contract or no multiple-contract flag.
- `rateSched == 'E-BULK'`: bulk tariff.
- `rateSched == 'E-LPT'`: load profile tariff.
- `saType == 'E-FIT'`: FIT service agreement.
- `billTag == 'Final Bill'`: final bill scenario.
- `billTag == 'Amended Bill'`: amended bill scenario.
- `billChars[CM-COPBT]`: copy bill scenario.
- `billChars[CM-MNBLR]`: manual bill/backcharge/adjustment scenario.
- `chargeType == 'MC'` or `unitIndicator == '(min)'`: minimum-charge scenario.
- `sqi == 'HVSDR ELIGIBILITY'`: HVSDR scenario.

## Reading Comms Conditions

Document conditions usually look like:

```text
$[?( ...boolean expression... )]
```

Inside the wrapper, expressions often combine:

- `&&`: AND
- `||`: OR
- `!`: NOT
- `empty true`: path should be missing or empty
- `empty false`: path should have at least one value
- `==` and `!=`: value comparisons
- `[?(@.field == 'value')]`: filtered nodes
- `[*]`: wildcard array traversal
- `$..path`: deep search

Prefer explaining conditions in plain gates rather than pasting a full giant
condition. Quote only the key fragments needed to justify the result.

## ATool Mapping Diagnostics

ATool's `Data -> Map...` and `Data -> Convert and Map...` workflows compare an
input JSON payload against the open AT.

After mapping:

- Triggered documents are blue.
- Untriggered documents are red.
- The Documents panel initially shows only triggered documents.
- `Show All` reveals failed documents too.
- Selecting a failed document shows `Match Details`.
- Field Manager can show mapped/unmapped fields.
- Layouts show mapping and condition pass/fail status.

For debugging, the Match Details section is usually more useful than guessing
from the condition string alone. It explains the overall logic and which clause
passed or failed.

## Clause Manager

ATool stores reusable clauses in package metadata. Clause Manager can compose
conditions from named clauses, raw fragments, and embedded clauses.

Composer syntax:

- `+` or `AND`: logical AND.
- `OR`, `||`, or `|`: logical OR.
- Parentheses: grouping.
- `RAW{...}`: raw condition fragment.
- `CLAUSE{exact clause name}`: explicit clause reference when the name has spaces
  or special characters.

Important caution: named ATool clauses and fields improve editing in ATool, but
Comms ultimately receives raw condition text in the AT wrapper format.

## Shared Package Editing

ATool supports local and shared package workflows. Shared packages can have edit
locks so two people do not unknowingly publish over each other.

Useful concepts:

- Get to Local: download a Comms package for local inspection/editing.
- Get to Shared/Edit: use a shared package area and acquire/resume an edit lock.
- Update Shared Package: save local edits back to the shared package area.
- Publish Package to Comms: publish the package back into Comms.
- Manual Unlock Shared Package: explicit override for stale locks.

When troubleshooting shared package issues, confirm:

- Which package/version folder is open.
- Whether the current user owns the edit lock.
- Whether the package is local, shared/edit, or shared/published.
- Whether unsaved AT edits (`*`) or unpublished package association changes (`!`)
  are present in the window title/status.

## Package Documents Manager

Package Documents Manager handles package-level document associations and order.
It is separate from the AT document tree.

It can:

- Show associated and unassociated documents.
- Reorder associated documents.
- Toggle Always Trigger.
- Add from the document catalog.
- Create a minimal AT document shell when needed.
- Remove an association without deleting the AT document.

If a document exists in `assembly-template.json` but does not render, check its
package association. If a document is associated but missing from the AT, check
whether a minimal shell exists or needs to be created.

## Safe File Handling

When Codex is investigating:

- Use `rg` for fast searching.
- Use `python3 -m json.tool` only for read-only validation/pretty-printing unless
  explicitly asked to write output.
- Do not run destructive git or filesystem commands.
- Do not modify files under `~/.atool/` unless the user asks.
- If generating a diagnostic artifact, write it under the repo root or `/tmp` and
  make clear that it is a report, not a source change.

When editing source:

- Keep changes scoped.
- Prefer existing ATool patterns.
- Remember `ATool.py` is large; search before changing.
- Run a syntax check at minimum:

```bash
python3 -m py_compile ATool.py
```

## Minimal Diagnostic Report Template

Use this shape when explaining trigger results:

```text
Document: CO-G1-CO19_v2
AT file: /path/to/assembly-template.json
Data file: /path/to/input.json

Result: PASS/FAIL

Key gates:
- Language: expected ENGLISH, found ENGLISH -> PASS
- Tariff: expected E-BULK, found E-BULK -> PASS
- Multiple contract: expected not true, found false -> PASS
- Scenario branch: expected one of final/complex/rebill/minimum/simple, found
  unitIndicator "(min)" -> PASS

Conclusion:
The document should trigger locally. If Comms did not render it, next check
package association/order/always-trigger state and whether the preview used this
same package version.
```

## Glossary

- **AT**: Assembly Template, usually `assembly-template.json`.
- **Comms**: Oracle Communications Cloud Service environment.
- **OCCS CLI**: command-line tool ATool calls for package, preview, conversion,
  config close, and migration workflows.
- **Document**: an AT document object, keyed by `$$Id`.
- **Layout**: a tree of content/iteration/field definitions inside a document.
- **Condition**: Comms trigger or layout condition in `$[?(...)]` format.
- **Clause**: reusable ATool expression stored in package metadata.
- **Mapping**: evaluating AT fields/document conditions/layouts against sample
  JSON data.
- **Package association**: package metadata linking documents into a package and
  defining order/always-trigger behavior.
- **Shared package**: package copy managed through ATool's shared package/edit
  lock workflow.
