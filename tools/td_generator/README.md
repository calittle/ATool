# Technical Design Generator

Create a Technical Design (TD) for a Comms document family. The report shows the documents that actually render for a chosen baseline bill, their layouts and content, conditions, fields, styles, and the scenarios used to test them.

This guide is written for the person maintaining the TD—not for someone maintaining the generator.

## Before you begin

### Using the ATool application

Open **Model → Generate Technical Design…**. You can create and maintain the
documentation plan without editing JSON:

1. Click **New**, or **Open…** to load an existing profile.
2. On **Documentation plan**, enter the family name and description, package,
   effective date and optional exact AT version. New plans start with the open
   package and its version when available; check these before generating.
3. Add one baseline row per **business case** (for example CO1 Domestic or CO3
   Staff). In **Comms documents**, enter the actual rendered template names,
   separated by commas, such as `RT_BILL, Backpage`. Multiple cases can map to
   the same documents. Add variants beneath their own baseline. Double-click
   cells to edit; **Move up/down** sets the case order and first-use document order.
4. In the document table, select **Compare cases and variants** or **Document
   only**. For comparisons, choose the **reference business case**: other case
   baselines are compared with it, and variants with their own case baseline.
   Document-only items need no reference case. Their structure, selection rules
   and metadata coverage remain in the TD, and expected baseline rendering is
   still verified. This is useful for shared inserts such as Backpage.
5. On **Files and generation**, select the sample root folder. Back on the plan,
   select a row and click **Choose input…** to fill in the scenario and filename.
6. Use the Comms cache configured in ATool User Settings, or select an override.
   Choose the output Markdown file, formats and generation options.
7. **Save** the profile for reuse, then click **Generate**. Progress and errors
   appear below; use **Open output folder** to find the results.

The saved JSON contains the family, package/date/version, ordered baselines and
variants, their Comms-document mappings and document reference cases. Sample and cache folders, output location, formats and run options are
remembered on this computer for each profile. Comms connection/session settings
come from ATool. **Save As…** creates another plan with the current local choices.
When sharing a profile, also provide its samples; the recipient selects local
sample/cache/output locations on first use.

Older profiles containing `scenarios`, `comms.resource_cache` and `occs` still
open. Their paths populate the controls (the app's configured cache takes
precedence). Saving migrates those machine-specific options to local preferences;
ATool creates a backup of the previous JSON. Unknown documentation fields are
preserved. Unsaved plan changes prompt you to save before closing or switching.

Older baseline entries using `document` migrate to a business case of the same
name mapped to that Comms document. No mapping to redesigned templates is guessed.
Change **Comms documents** explicitly after checking the rendered metadata.
Each declared document must render for that case's baseline; additional returned
documents are excluded unless explicitly mapped. Include `Backpage` in the mapping
when it belongs in the TD.

For example, shared-template profiles use this structure (input names are examples):

```json
{
  "family": "Residential Tariff",
  "comms": {"package": "CLP_bills", "effective_date": "2026-11-19"},
  "document_references": {"RT_BILL": "CO1"},
  "document_comparisons": {"RT_BILL": "compare", "Backpage": "document_only"},
  "baselines": [
    {"case": "CO1", "documents": ["RT_BILL", "Backpage"], "label": "Domestic",
     "scenario": "Regular", "input": "domestic.xml",
     "variants": [{"scenario": "Prorate", "input": "domestic-prorate.xml"}]},
    {"case": "CO3", "documents": ["RT_BILL", "Backpage"], "label": "Staff",
     "scenario": "Regular", "input": "staff.xml", "variants": []}
  ]
}
```

The TD describes each Comms document once. Scope lists all business cases and
inputs. Comparisons inspect document metadata recursively, alongside condition
results, including nested layouts, contents and fields. They separate:

- **Structural / conditional** changes: added/removed/reordered elements, style
  or markup changes, selected conditional includes, and changed trigger clauses.
- **Data-only** changes: changed values inside the same `comms-data` definition
  and matching surrounding markup/text, summarized as a count. Explicit field
  value differences are summarized too; customer values are not copied.
- **Unclassified rendered content**: text outside mapped fields or ambiguous
  markup changes that cannot safely be called data-only. These remain visible
  for review.

Up to 20 changed paths per detailed category are shown, plus the remaining count.
The full saved metadata remains available. Metadata does not establish
pixel-for-pixel visual equality. Document-only coverage lists configured content
options and conditions with the cases in which Comms metadata exposed them;
unseen options are marked **Not observed in supplied metadata**, not assumed tested.
Omitting `document_comparisons` preserves the previous comparison behavior.

The standalone application includes Python, the DOCX renderer, Node and OCCS CLI.
Use ATool's existing Comms login/settings for fresh metadata. PDF still requires
LibreOffice. Keep profiles, samples, downloaded resources and output in ordinary
user folders outside the application bundle. Relative scenario paths resolve
beside the profile, or one level above it for existing `profiles/` + `samples/`
distributions. Relative cache paths in the dialog resolve beside the profile.

Choose **Reuse metadata beside the output file** to work with existing evidence.
XML conversion defaults to reusing JSON; **Use existing JSON only** prevents
conversion. Refresh conversions explicitly after changing XML. Content indexes
are rebuilt by default so refreshed resources are reflected in the report.
Leave the dialog open until generation completes.

To maintain an existing TD, open its profile, update the baseline/variant table
or package date/version, refresh the Comms cache as needed, and generate again.
Paths and run choices are restored when you reopen that profile.
The dialog automatically reopens the last profile you opened or saved, including
its local paths and run choices. **New** still starts a blank plan. If the last
profile has moved, been deleted or cannot be read, the dialog opens a blank plan
and explains the problem; use **Open…** to locate its replacement.

### Running the command-line tool

Profiles saved by the app omit local paths. Supply them on the command line:

```bash
python3 td_generator.py generate \
  --profile /path/to/profile.json \
  --samples-root /path/to/samples \
  --resource-cache /path/to/comms-cache \
  --source cached \
  --out /path/to/generated/design.md
```

The path options also override legacy profile paths. Existing command-line
profiles with `scenarios` and `comms.resource_cache` continue to work. Relative
scenario paths are checked beside the profile, then one level above for the
older `profiles/` + `samples/` structure; relative cache paths are profile-relative.

You need:

- A local copy of the ATool repository, including this `tools/td_generator` folder.
- Python 3.11 or later. Install the one report-formatting dependency once:

  ```bash
  python3 -m pip install -r requirements.txt
  ```

- OCCS CLI set up and logged in to the target Comms environment.
- A downloaded Comms resource cache for the package. This is the local reference copy of the package, documents, layouts, contents, and styles.
- A folder of representative bill inputs, arranged into scenario folders.

To create PDFs, LibreOffice must also be installed and available as `soffice`.

The TD generator does not change Comms. It reads the cached resources and, when requested, asks Comms to render read-only metadata for the sample inputs.

## First-time setup

### 1. Download the Comms resource cache

Use OCCS CLI to download the resources for the environment and package you want to document. Keep the output in a known location; the profile will point to that location.

```bash
occs get-everything -o /path/to/comms-cache
```

If you already have a cache, make sure it includes the package, documents, layouts, contents, and styles. Refreshing contents with the current CLI is important: it also saves the style-class relationships used by the TD.

```bash
occs list-contents -o /path/to/comms-cache/contents
```

### 2. Arrange your sample inputs

Place sample bill XML or JSON files in one top-level folder per business scenario. The folder name becomes the scenario name in the TD. You can put more than one input file in each scenario folder.

```text
samples/example/
├── Regular/
│   ├── example-baseline.xml
│   └── example-secondary.xml
└── Final/
    └── example-final.xml
```

Choose one **baseline** input for each business case. It should render that case's
expected Comms documents. Map each case to those documents explicitly and choose
one reference case per document. Other inputs become variants of their own case.

### 3. Create or update the profile

Copy `profiles/example-profile.json` to a new local profile, then update the package, date, cache location, sample root, and the explicit baseline plan. Local profiles and samples are ignored by Git.

```json
{
  "family": "Example document family",
  "comms": {
    "package": "EXAMPLE_PACKAGE",
    "effective_date": "2026-01-01",
    "reference_version": "1.0",
    "resource_cache": "/path/to/comms-cache"
  },
  "scenarios": "samples/example",
  "baselines": [
    {
      "document": "EXAMPLE_DOCUMENT",
      "label": "Example baseline",
      "scenario": "Regular",
      "input": "example-baseline.xml",
      "variants": [
        {
          "scenario": "Final",
          "input": "example-final.xml"
        }
      ]
    }
  ]
}
```

The example above shows the legacy one-case/one-document format, which remains
supported. For shared templates, use `case`, `documents` and `document_references`
as shown in the application section. Add one baseline entry per business case,
with the exact scenario/input and relevant variants. Each variant is compared
with its own case baseline. Comms documents are ordered by their first appearance
in the case mappings and described once, even when multiple cases use them.

The generator verifies that every declared baseline input actually renders its declared document. It does not infer missing family members from document names or include other documents rendered by the same bill.

`reference_version` records the exact Assembly Template version used for the field and clause glossary. `effective_date` is the Comms date used to select the active package resources and render the sample bills.

## Generate your first TD

From this folder, run:

```bash
python3 td_generator.py generate \
  --profile profiles/my-profile.json \
  --out generated/my-profile.md
```

For a first run, the generator will:

1. Find every scenario and input below `scenarios`.
2. Convert XML inputs to reusable JSON where needed.
3. Render the declared baseline and variant inputs as Comms metadata.
4. Verify each case baseline renders its mapped Comms documents, then group cases under the explicitly mapped documents.
5. Read the cached Comms resources to explain document, layout, content, field, and style relationships.
6. Write the Markdown TD and its supporting evidence files.

The default output is Markdown only, which is best while reviewing changes. Open `generated/my-profile.md` in any Markdown viewer.

When the content is approved, create the delivery formats:

```bash
python3 td_generator.py generate \
  --profile profiles/my-profile.json \
  --out generated/my-profile.md \
  --formats md,docx,pdf
```

### Create DOCX or PDF from an existing Markdown TD

If the Markdown TD has already been generated and reviewed, you can create or refresh its DOCX and PDF without converting samples, calling Comms, or regenerating the TD content:

```bash
python3 render_td.py \
  --markdown generated/my-profile.md \
  --docx generated/my-profile.docx \
  --pdf generated/my-profile.pdf
```

Omit the `--pdf` line when you only need a DOCX. PDF creation requires LibreOffice (`soffice`).

## What to review in the TD

- **Scope** confirms every family member document plus its baseline and variant test cases.
- **Documents** contains each mapped Comms document once, in first-use order, with per-case comparisons and variants.
- Each document shows trigger conditions, the resolved document → layout → content structure, fields in their content context, and scenario differences.
- **Glossary** provides one definition per field and style, with links back to each use.

If an expected document does not appear, start with the baseline input: Comms did not render it for that bill. If a scenario differs unexpectedly, review that scenario's input and the conditions shown in its document section.

## Maintaining the TD

Use this checklist after configuration changes.

### Changed a document, layout, content, or style

1. Download a fresh Comms resource cache, or refresh the affected resources. Refresh contents with `list-contents` so style-class associations are included.
2. Update the profile's `effective_date` or `reference_version` if those changed.
3. Rebuild the TD's local lookup index and regenerate the Markdown report:

```bash
python3 td_generator.py generate \
  --source cached --render-evidence cached \
  --xml-conversion never --rebuild-resource-index \
  --profile profiles/my-profile.json \
  --out generated/my-profile.md
```

Use `--render-evidence metadata` instead of `cached` when you want Comms to render every sample again and recalculate scenario differences. This is the normal choice after a real configuration change:

```bash
python3 td_generator.py generate \
  --source cached --render-evidence metadata \
  --rebuild-resource-index \
  --profile profiles/my-profile.json \
  --out generated/my-profile.md
```

### Added or changed a sample scenario

Add, replace, or remove input files under the appropriate scenario folder. No profile edit is needed unless the baseline changes. Then regenerate with `--render-evidence metadata` so the scenario is evaluated by Comms.

### Changed a baseline or variant test case

Update the corresponding entry in `baselines`, then generate with `--render-evidence metadata`. Adding a family member requires adding its own baseline entry and representative input; it will not be discovered automatically.

### XML input has changed

The generator reuses converted JSON by default. Use `--xml-conversion always` to force a new JSON conversion for all XML inputs, or remove just the matching file under `generated/converted-inputs` and use the normal command.

## Common commands

| Need | Use |
| --- | --- |
| Fast Markdown rebuild from saved resources and renders | `--source cached --render-evidence cached --xml-conversion never` |
| Re-test all samples in Comms | `--source cached --render-evidence metadata` |
| Rebuild after refreshing the resource cache | Add `--rebuild-resource-index` |
| Force fresh XML-to-JSON conversion | Add `--xml-conversion always` |
| Make Word and PDF deliverables | Add `--formats md,docx,pdf` |

## If something looks wrong

- **A document is missing or generation stops:** confirm the declared document renders for its own baseline input and effective date.
- **A field says `ERROR: definition not found (AT)`:** check the field name in the content `$Data{"Id":"..."}` and confirm it exists in the Assembly Template field list or an iterator for the profile's version.
- **A style says `ERROR: reference not found (output)`:** refresh the styles and contents resource cache, then regenerate with `--rebuild-resource-index`.
- **A new XML input cannot be used:** confirm OCCS CLI is logged in; XML conversion consumes a session token, so the generator intentionally converts XML files one at a time.

## Technical reference

The generated `resource-cache-index` folder is disposable. It is rebuilt automatically when absent, or explicitly with `--rebuild-resource-index`; it never changes the Comms resource cache. Supporting `.evidence.json` output is a machine-readable record of the TD source facts. The generator uses ATool's shared condition evaluator for diagnostic explanation, while Comms metadata remains the authority for what actually renders.
