# Technical Design Generator

Create a Technical Design (TD) for a Comms document family. The report shows the documents that actually render for a chosen baseline bill, their layouts and content, conditions, fields, styles, and the scenarios used to test them.

This guide is written for the person maintaining the TD—not for someone maintaining the generator.

## Before you begin

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

Choose one input as the **baseline**. It should be a normal, representative bill that renders the documents you want the TD to describe. The documents returned for this one bill set the scope and order of the TD. Other samples are used to describe differences from that baseline.

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

Add one `baselines` entry for every family-member document you want in the TD, in the order it should appear. Each entry names the document Comms must render, plus the exact scenario and input that act as its baseline. Add only business-relevant `variants`; each is compared with that document's own baseline.

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
4. Verify each declared baseline renders its expected document, then use the profile's baseline order as the TD scope.
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
- **Documents** contains only the profile's declared baseline documents, in profile order.
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
