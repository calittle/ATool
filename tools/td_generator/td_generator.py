#!/usr/bin/env python3
"""Generate an execution-derived OCCS Technical Design using ATool evaluation."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from atool_core.condition_evaluator import ConditionEvaluator  # noqa: E402
from atool_core.td_evidence import ScenarioEvidence, TechnicalDesignEvidence  # noqa: E402


class AToolConditionEvaluator:
    """Headless facade over the shared condition logic used by ATool."""

    def __init__(self) -> None:
        self._evaluator = ConditionEvaluator()

    def matches(self, condition: str, payload: object) -> bool:
        return self._evaluator._evaluate_document_condition(condition, payload)


def discover_inputs(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        (item for item in folder.rglob("*") if item.is_file() and item.suffix.lower() in {".json", ".xml"}),
        key=lambda item: str(item).casefold(),
    )


def discover_scenarios(scenario_root: str, profile_path: Path) -> list[dict[str, Any]]:
    root = Path(scenario_root).expanduser()
    if not root.is_absolute():
        root = (Path(__file__).resolve().parent / root).resolve()
    if not root.exists():
        raise ValueError(f"Scenario root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Scenario root is not a folder: {root}")
    return [
        {"name": folder.name, "folder": folder, "inputs": discover_inputs(folder)}
        for folder in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold())
    ]


def declared_baselines(profile: dict[str, Any], scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the deliberately selected document baselines and variants."""
    entries = profile.get("baselines")
    if entries is None:
        return []
    if not isinstance(entries, list) or not entries:
        raise ValueError("Profile baselines must be a non-empty list.")
    available = {
        str(scenario["name"]): {item.name: item for item in scenario.get("inputs", [])}
        for scenario in scenarios
    }
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Baseline {index} must be an object.")
        document = str(raw.get("document", "")).strip()
        scenario = str(raw.get("scenario", "")).strip()
        input_name = str(raw.get("input", "")).strip()
        if not document or not scenario or not input_name:
            raise ValueError(f"Baseline {index} must specify document, scenario, and input.")
        if input_name not in available.get(scenario, {}):
            raise ValueError(f"Baseline {document} references input {scenario} / {input_name}, which was not discovered under scenarios.")
        variants: list[dict[str, str]] = []
        for variant_index, variant in enumerate(raw.get("variants", []) or [], start=1):
            if not isinstance(variant, dict):
                raise ValueError(f"Baseline {document} variant {variant_index} must be an object.")
            variant_scenario = str(variant.get("scenario", "")).strip()
            variant_input = str(variant.get("input", "")).strip()
            if not variant_scenario or not variant_input:
                raise ValueError(f"Baseline {document} variant {variant_index} must specify scenario and input.")
            if variant_input not in available.get(variant_scenario, {}):
                raise ValueError(f"Baseline {document} variant references input {variant_scenario} / {variant_input}, which was not discovered under scenarios.")
            variants.append({"scenario": variant_scenario, "input": variant_input, "label": str(variant.get("label", "")).strip()})
        result.append({"document": document, "scenario": scenario, "input": input_name, "label": str(raw.get("label", "")).strip(), "variants": variants})
    if len({item["document"] for item in result}) != len(result):
        raise ValueError("Each profile baseline must declare a different document.")
    return result


def load_sample(sample: Path) -> object:
    with sample.open(encoding="utf-8") as source:
        return json.load(source)


def default_occs_cli() -> Path:
    return REPOSITORY_ROOT.parent / "ccs-tools" / "OCCS-CLI" / "bin" / "occs.js"


def normalise_fields(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Return top-level and iterator field definitions from the Assembly Template."""
    usage: defaultdict[tuple[str, str, bool], set[str]] = defaultdict(set)
    for document in template.get("Documents", []):
        if not isinstance(document, dict):
            continue
        document_id = str(document.get("$$Id", "(unnamed document)"))
        for layout in document.get("Layouts", []):
            if not isinstance(layout, dict):
                continue
            for content in layout.get("Contents", []):
                if not isinstance(content, dict):
                    continue
                iteration = content.get("Iteration")
                if not isinstance(iteration, dict):
                    continue
                for field in iteration.get("Fields", []):
                    if not isinstance(field, dict):
                        continue
                    key = (str(field.get("Name", "")), str(field.get("Path", "")), bool(field.get("Mandatory", False)))
                    usage[key].add(document_id)
    result = []
    seen: set[tuple[str, str, bool]] = set()
    for item in template.get("Fields", []):
        if not isinstance(item, dict):
            continue
        key = (str(item.get("Name", "")), str(item.get("Path", "")), bool(item.get("Mandatory", False)))
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "name": key[0], "path": key[1], "mandatory": key[2],
            "description": str(item.get("Descr", item.get("Description", ""))), "iterator": "",
            "documents": sorted(usage.get(key, set())),
        })
    # Iterator fields are not global AT Fields, but they are nevertheless
    # authored symbols. Index them so blob references such as `charge` and
    # `meterIter` resolve to their iterator base/path.
    for document in template.get("Documents", []):
        if not isinstance(document, dict):
            continue
        document_id = str(document.get("$$Id", "(unnamed document)"))
        for layout in document.get("Layouts", []):
            for content in layout.get("Contents", []) if isinstance(layout, dict) else []:
                iteration = content.get("Iteration") if isinstance(content, dict) else None
                if not isinstance(iteration, dict):
                    continue
                base = str(iteration.get("Path", ""))
                for item in iteration.get("Fields", []):
                    if not isinstance(item, dict):
                        continue
                    key = (str(item.get("Name", "")), str(item.get("Path", "")), bool(item.get("Mandatory", False)))
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append({"name": key[0], "path": key[1], "mandatory": key[2], "description": "", "iterator": base, "documents": [document_id]})
    return result


def load_atool_clauses(profile: dict[str, Any], source: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Load ATool's persisted clause library when the live template has none."""
    configured = profile.get("atool_metadata")
    if configured:
        metadata_path = Path(str(configured)).expanduser()
    else:
        package = str(source.get("package", "")).strip().lower().replace(" ", "_")
        metadata_path = Path.home() / ".atool" / f".{package}.meta.json"
    if not metadata_path.exists():
        return [], None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], str(metadata_path)
    raw = payload.get("clause_library", []) if isinstance(payload, dict) else []
    clauses = []
    for clause in raw if isinstance(raw, list) else []:
        if not isinstance(clause, dict) or not str(clause.get("name", "")).strip():
            continue
        clauses.append({
            "name": str(clause["name"]), "description": str(clause.get("description", "")),
            "expression": str(clause.get("expression", "")), "updated_at": str(clause.get("updated_at", "")),
        })
    return sorted(clauses, key=lambda item: item["name"].casefold()), str(metadata_path)


def rendered_documents(metadata_file: Path) -> list[str]:
    """Extract the exact ordered document names returned by Comms METADATA."""
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    package = metadata.get("Package", {}) if isinstance(metadata, dict) else {}
    documents = package.get("Documents", []) if isinstance(package, dict) else []
    return [str(document.get("Name")) for document in documents if isinstance(document, dict) and document.get("Name")]


def preview_metadata(sample: Path, profile: dict[str, Any], destination: Path) -> list[dict[str, Any]]:
    """Run Comms METADATA for one source input and preserve only compact facts."""
    comms, occs = profile.get("comms", {}), profile.get("occs", {})
    package = str(comms.get("package", "")).strip()
    if not package:
        raise ValueError("comms.package is required for render evidence")
    cli = Path(str(occs.get("cli") or default_occs_cli())).expanduser()
    timeout_ms = int(occs.get("timeout_ms", 360000))
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{sample.stem}.metadata.json"
    command = ["node", str(cli), "preview", "--package", package, "--input", str(sample), "--render-type", "METADATA", "--output", str(output), "--timeout", str(timeout_ms), "--verbose"]
    effective_date = str(comms.get("effective_date", "")).strip()
    if effective_date:
        command.extend(["--effective-date", effective_date])
    if occs.get("session"):
        command.extend(["--session", str(occs["session"])])
    result = subprocess.run(command, capture_output=True, text=True, timeout=(timeout_ms / 1000) + 30)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise ValueError(f"Comms METADATA preview failed: {detail or f'exit code {result.returncode}'}")
    metadata_files = sorted(destination.glob(f"{sample.stem}*.metadata.json"), key=lambda item: item.name.casefold())
    results = []
    for item in metadata_files:
        generated_input = Path(str(item).replace(".metadata.json", ".generated-input.json"))
        results.append({"metadata": str(item), "documents": rendered_documents(item), "generated_input": str(generated_input) if generated_input.exists() else None})
    return results


def cached_metadata(sample: Path, destination: Path) -> list[dict[str, Any]]:
    return [{"metadata": str(item), "documents": rendered_documents(item), "generated_input": None}
            for item in sorted(destination.glob(f"{sample.stem}*.metadata.json"), key=lambda item: item.name.casefold())]


def process_input(scenario_name: str, source_input: Path, payload_file: Path, template: dict[str, Any], profile: dict[str, Any], output_path: Path, render_evidence_mode: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Produce local trigger observations and Comms render evidence for one input."""
    observations: list[dict[str, Any]] = []
    renders: list[dict[str, Any]] = []
    try:
        if render_evidence_mode in {"metadata", "cached"}:
            destination = output_path.parent / "render-evidence" / scenario_name
            raw_renders = preview_metadata(payload_file, profile, destination) if render_evidence_mode == "metadata" else cached_metadata(payload_file, destination)
            for render in raw_renders:
                renders.append({"scenario": scenario_name, "input": str(source_input), "payload": str(payload_file), **render})
        samples = [load_sample(payload_file)]
        evaluator = AToolConditionEvaluator()
        for transaction_number, sample in enumerate(samples, start=1):
            observations.append({"scenario": scenario_name, "file": source_input, "payload": payload_file, "transaction": transaction_number if len(samples) > 1 else None, "documents": evaluate(template, sample, evaluator)})
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        observations.append({"scenario": scenario_name, "file": source_input, "payload": payload_file, "error": str(error)})
        if render_evidence_mode in {"metadata", "cached"}:
            renders.append({"scenario": scenario_name, "input": str(source_input), "payload": str(payload_file), "error": str(error)})
    return observations, renders


def fetch_live_bundle(comms: dict[str, Any], occs: dict[str, Any], snapshot_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Download the current package bundle and retain it as TD evidence."""

    package = str(comms.get("package", "")).strip()
    # A version is retained only as the snapshot/reference identifier. Preview
    # evaluation is package + effective date, never this reference version.
    version = str(comms.get("reference_version", comms.get("version", "latest"))).strip() or "latest"
    if not package:
        raise ValueError("comms.package is required for a live configuration snapshot")
    cli = Path(str(occs.get("cli") or default_occs_cli())).expanduser()
    timeout_ms = int(occs.get("timeout_ms", 360000))
    command = ["node", str(cli), "package"]
    if occs.get("session"):
        command.extend(["--session", str(occs["session"])])
    command.extend(["get", package, version, "--output", str(snapshot_dir), "--force", "--timeout", str(timeout_ms), "--json"])
    result = subprocess.run(command, capture_output=True, text=True, timeout=(timeout_ms / 1000) + 30)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise ValueError(f"Live Comms package download failed: {detail or f'exit code {result.returncode}'}")
    template_file = snapshot_dir / "assembly-template.json"
    associations_file = snapshot_dir / "document-associations.json"
    if not template_file.exists():
        raise ValueError(f"Live Comms package bundle did not contain {template_file.name}")
    associations_payload = json.loads(associations_file.read_text(encoding="utf-8")) if associations_file.exists() else []
    associations = associations_payload.get("associations", []) if isinstance(associations_payload, dict) else associations_payload
    manifest_file = snapshot_dir / "occs-package.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    source = {
        "mode": "live-comms", "package": package, "version": version,
        "effectiveDate": str(comms.get("effective_date", "")),
        "snapshot": str(snapshot_dir), "manifest": manifest,
        # This is written by `occs package get` when it finishes pulling the
        # bundle; it is not a local file modification-time approximation.
        "cachedAt": manifest.get("createdAt") or datetime.now(UTC).isoformat(),
        "associationCount": len(associations),
    }
    return json.loads(template_file.read_text(encoding="utf-8")), associations, source


def load_resource_cache(comms: dict[str, Any]) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Resolve the package's Assembly Template from one OCCS resource cache."""
    cache = Path(str(comms.get("resource_cache", ""))).expanduser()
    package = str(comms.get("package", "")).strip()
    version = str(comms.get("reference_version", "")).strip()
    effective_date = str(comms.get("effective_date", "")).strip()
    if not cache.is_dir():
        raise ValueError("comms.resource_cache must point to an OCCS resource-cache directory")
    if not package or not effective_date:
        raise ValueError("comms.package and comms.effective_date are required to resolve the cached Assembly Template")
    master_path = cache / "packages" / package / f"{package}_master.json"
    if not master_path.exists():
        raise ValueError(f"Resource cache did not contain package master {master_path}")
    master = json.loads(master_path.read_text(encoding="utf-8"))
    candidates: list[tuple[str, str]] = []
    for row in master.get("CommunicationPackageMasterVersions", []):
        record = row.get("CommunicationPackageVersionConfigRec", {}) if isinstance(row, dict) else {}
        short_name = str(record.get("CommunicationPackageVersionConfigInfo", {}).get("ShortName", ""))
        active_dates = [str(item.get("EffDtTm", ""))[:10] for item in record.get("Status", {}).get("Items", []) if item.get("StatusCode") == "Active" and str(item.get("EffDtTm", ""))[:10] <= effective_date]
        if short_name and active_dates:
            candidates.append((max(active_dates), short_name))
    effective_version = max(candidates, default=("", ""))[1]
    if not effective_version:
        raise ValueError(f"No active cached {package} package version was found for {effective_date}")
    if version and version != effective_version:
        raise ValueError(f"Configured reference_version {version!r} does not match effective {effective_date} package version {effective_version!r}")
    version = effective_version
    package_dir = cache / "packages" / package / "versions" / version
    template_path = package_dir / "AssemblyTemplate.json"
    version_path = package_dir / f"{version}.json"
    if not template_path.exists():
        raise ValueError(f"Resource cache did not contain {template_path}")
    version_data = json.loads(version_path.read_text(encoding="utf-8")) if version_path.exists() else {}
    source = {
        "mode": "resource-cache", "package": package, "version": version,
        "effectiveDate": effective_date, "resourceCache": str(cache),
        "packageCache": str(package_dir), "cachedAt": datetime.fromtimestamp(template_path.stat().st_mtime, UTC).isoformat(),
        "packageVersion": version_data.get("CommunicationPackageVersionConfigInfo", {}),
    }
    return json.loads(template_path.read_text(encoding="utf-8")), cache, source


def refresh_document_graph(source: dict[str, Any], output_dir: Path, document_names: list[str]) -> None:
    """Refresh the Comms document/layout graph for the baseline-rendered docs."""
    snapshot = Path(str(source.get("snapshot", "")))
    associations = snapshot / "document-associations.json"
    if not associations.exists() or not document_names:
        return
    names_file = output_dir / "baseline-rendered-documents.json"
    names_file.write_text(json.dumps(document_names, indent=2) + "\n", encoding="utf-8")
    script = Path(__file__).with_name("fetch_document_graph.mjs")
    result = subprocess.run(
        ["node", str(script), str(associations), str(output_dir / "document-graph.json"), str(names_file)],
        capture_output=True, text=True, timeout=360,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise ValueError(f"Comms document graph refresh failed: {detail or f'exit code {result.returncode}'}")


def refresh_content_catalog(output_dir: Path, document_graph: dict[str, Any], document_names: list[str]) -> None:
    """Fetch the live content closure used by the baseline-rendered documents."""
    content_names: set[str] = set()
    for document_name in document_names:
        content_names.update(graph_content_names(document_graph.get("documents", {}).get(document_name, {}), document_graph))
    if not content_names:
        return
    names_file = output_dir / "baseline-rendered-contents.json"
    names_file.write_text(json.dumps(sorted(content_names), indent=2) + "\n", encoding="utf-8")
    script = Path(__file__).with_name("fetch_content_blobs.mjs")
    result = subprocess.run(
        ["node", str(script), str(names_file), str(output_dir / "scoped-content-catalog")],
        capture_output=True, text=True, timeout=900,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise ValueError(f"Comms content catalog refresh failed: {detail or f'exit code {result.returncode}'}")


def resource_document_graph(cache: Path, document_names: list[str], effective_date: str) -> dict[str, Any]:
    """Build a document/layout graph directly from the downloaded OCCS resources."""
    def effective(item: dict[str, Any]) -> str:
        entries = item.get("Status", {}).get("Items", []) if isinstance(item, dict) else []
        dates = [str(row.get("EffDtTm", "")) for row in entries if row.get("StatusCode") == "Active" and str(row.get("EffDtTm", ""))[:10] <= effective_date]
        return max(dates, default="")
    def styles(items: list[dict[str, Any]]) -> list[dict[str, str]]:
        result = []
        for item in items:
            rel = item.get("CommunicationLayoutConfigCommunicationStyleConfigRelRec", {}).get("CommunicationLayoutConfigCommunicationStyleConfigRelInfo", {})
            info = item.get("CommunicationStyleConfigRec", {}).get("CommunicationStyleConfigInfo", {})
            result.append({"name": str(info.get("ShortName", "")), "className": str(rel.get("StyleClassName", ""))})
        return [item for item in result if item["name"] or item["className"]]
    layout_files = list((cache / "layouts").glob("*/*.json"))
    layouts: dict[str, dict[str, Any]] = {}
    for file in layout_files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
            info = payload.get("CommunicationLayoutConfigRec", {}).get("CommunicationLayoutConfigInfo", {})
            uuid = str(payload.get("CommunicationLayoutConfigRec", {}).get("CommunicationLayoutConfigUuid", ""))
            if not uuid:
                continue
            contents = []
            for item in payload.get("CommunicationLayoutContents", []):
                rel = item.get("CommunicationLayoutConfigCommunicationContentConfigRelRec", {}).get("CommunicationLayoutConfigCommunicationContentConfigRelInfo", {})
                contents.append({"name": str(item.get("ShortName", "")), "index": rel.get("ContentRelIndex", 0), "area": str(rel.get("StyleAreaName", ""))})
            children = []
            for item in payload.get("CommunicationLayoutLayouts", []):
                rel = item.get("CommunicationLayoutConfigCommunicationLayoutConfigRelRec", {}).get("CommunicationLayoutConfigCommunicationLayoutConfigRelInfo", {})
                children.append({"uuid": str(rel.get("RelCommunicationLayoutConfigUuid", "")), "name": str(item.get("ShortName", "")), "index": rel.get("LayoutRelIndex", 0), "area": str(rel.get("StyleAreaName", ""))})
            layouts[uuid] = {"uuid": uuid, "name": str(info.get("ShortName", "")), "type": str(info.get("LayoutType", "Unknown")), "styles": styles(payload.get("CommunicationLayoutStyles", [])), "contents": sorted(contents, key=lambda x: x["index"]), "childLayouts": sorted(children, key=lambda x: x["index"])}
        except (OSError, json.JSONDecodeError):
            continue
    documents: dict[str, Any] = {}
    for wanted in document_names:
        candidates = []
        for file in (cache / "documents").glob("*/versions/*.json"):
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
                info = payload.get("CommunicationDocumentConfigRec", {}).get("CommunicationDocumentConfigInfo", {})
                if str(info.get("ShortName", "")) == wanted:
                    candidates.append((effective(payload.get("CommunicationDocumentVersionConfigRec", {})), payload))
            except (OSError, json.JSONDecodeError):
                continue
        if not candidates:
            continue
        _, payload = max(candidates, key=lambda pair: pair[0])
        info = payload.get("CommunicationDocumentConfigRec", {}).get("CommunicationDocumentConfigInfo", {})
        roots = []
        for item in payload.get("CommunicationDocumentVersionLayouts", []):
            rel = item.get("CommunicationDocumentVersionConfigCommunicationLayoutConfigRelRec", {}).get("CommunicationDocumentVersionConfigCommunicationLayoutConfigRelInfo", {})
            layout_info = item.get("CommunicationLayoutConfigRec", {}).get("CommunicationLayoutConfigInfo", {})
            roots.append({"uuid": str(rel.get("CommunicationLayoutConfigUuid", "")), "name": str(layout_info.get("ShortName", "")), "index": rel.get("LayoutRelIndex", 0), "placement": str(rel.get("LayoutPlacement", ""))})
        documents[wanted] = {"description": str(info.get("Desc", "")), "version": str(payload.get("CommunicationDocumentVersionConfigRec", {}).get("CommunicationDocumentVersionConfigInfo", {}).get("ShortName", "")), "styles": styles(payload.get("CommunicationDocumentVersionStyles", [])), "roots": sorted(roots, key=lambda x: x["index"])}
    return {"documents": documents, "nodes": layouts}


def convert_xml_sample(sample: Path, occs: dict[str, Any]) -> list[object]:
    """Convert one XML sample through live OCCS and return every transaction."""

    cli = Path(str(occs.get("cli") or default_occs_cli())).expanduser()
    if not cli.exists():
        raise ValueError(f"OCCS CLI was not found: {cli}")
    timeout_ms = int(occs.get("timeout_ms", 360000))
    with tempfile.TemporaryDirectory(prefix="atool-td-convert-") as temporary_directory:
        output = Path(temporary_directory) / "converted.json"
        command = ["node", str(cli), "convertxml", "--input", str(sample), "--output", str(output), "--timeout", str(timeout_ms)]
        if occs.get("session"):
            command.extend(["--session", str(occs["session"])])
        result = subprocess.run(command, capture_output=True, text=True, timeout=(timeout_ms / 1000) + 30)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().replace("\n", " ")
            raise ValueError(f"OCCS XML conversion failed: {detail or f'exit code {result.returncode}'}")
        converted = [output] if output.exists() else list(Path(temporary_directory).rglob("*.json"))
        if not converted:
            raise ValueError("OCCS XML conversion produced no JSON files")
        return [load_sample(file) for file in sorted(converted, key=lambda file: file.name.casefold())]


def convert_xml_to_files(sample: Path, occs: dict[str, Any], destination: Path, mode: str = "auto") -> list[Path]:
    """Persist every converter result so later Comms calls can use JSON only."""
    cli = Path(str(occs.get("cli") or default_occs_cli())).expanduser()
    timeout_ms = int(occs.get("timeout_ms", 360000))
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{sample.stem}.json"
    # A previous successful serial conversion is persisted input evidence.
    # `auto` reuses it; `always` explicitly refreshes it; `never` makes a
    # cached JSON conversion a prerequisite for XML inputs.
    if mode not in {"auto", "always", "never"}:
        raise ValueError(f"Unsupported XML conversion mode: {mode}")
    existing = [item for item in sorted(destination.glob(f"{sample.stem}*.json"), key=lambda item: item.name.casefold()) if item.stat().st_size]
    if existing and mode != "always":
        # OCCS may suffix a converted file with a transaction identifier.
        # One XML source is represented by its most recently persisted result.
        return [max(existing, key=lambda item: item.stat().st_mtime)]
    if mode == "never":
        raise ValueError(f"No cached JSON conversion exists for {sample.name}; run with --xml-conversion auto or always.")
    command = ["node", str(cli), "convertxml", "--input", str(sample), "--output", str(output), "--timeout", str(timeout_ms)]
    if occs.get("session"):
        command.extend(["--session", str(occs["session"])])
    result = subprocess.run(command, capture_output=True, text=True, timeout=(timeout_ms / 1000) + 30)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise ValueError(f"OCCS XML conversion failed: {detail or f'exit code {result.returncode}'}")
    converted = [output] if output.exists() else sorted(destination.glob(f"{sample.stem}*.json"), key=lambda item: item.name.casefold())
    if not converted:
        raise ValueError("OCCS XML conversion produced no JSON files")
    return converted


def evaluate(template: dict[str, Any], sample: object, evaluator: AToolConditionEvaluator) -> list[dict[str, Any]]:
    triggered: list[dict[str, Any]] = []
    for document in template.get("Documents", []):
        if not isinstance(document, dict) or not evaluator.matches(str(document.get("Condition", "")), sample):
            continue
        contents: list[str] = []
        for layout in document.get("Layouts", []):
            if not isinstance(layout, dict):
                continue
            for content in layout.get("Contents", []):
                if isinstance(content, dict) and content.get("Condition") and evaluator.matches(str(content["Condition"]), sample):
                    contents.append(f"{layout.get('$$Id', '(unnamed layout)')} / {content.get('$$Id', '(unnamed content)')}")
        triggered.append({
            "id": str(document.get("$$Id", "(unnamed document)")),
            "description": str(document.get("Descr", "")),
            "layout_count": len(document.get("Layouts", [])),
            "conditional_content": contents,
        })
    return triggered


def escape(value: object, *, escape_dollar: bool = False) -> str:
    """Escape plain Markdown table text without altering code-formatted paths."""
    result = str(value or "").replace("|", "\\|").replace("\n", " ")
    return result.replace("$", "\\$") if escape_dollar else result


def condition_atoms(condition: str) -> list[str]:
    """Split a condition into readable top-level AND/OR constituent expressions."""
    evaluator = ConditionEvaluator()
    text = evaluator._extract_condition_body(condition).strip()
    for operator in ("&&", "||"):
        parts = evaluator._split_top_level_operator(text, operator)
        if len(parts) > 1:
            return [part.strip() for part in parts if part.strip()]
    return [text] if text else []


def clause_matches(condition: str, clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = "".join(condition.split())
    return [clause for clause in clauses if clause.get("expression") and "".join(str(clause["expression"]).split()) in compact]


def resolve_iterator_field_path(iterator_path: str, field_path: str) -> str:
    if field_path.startswith("$."):
        return f"{iterator_path}.{field_path[2:]}"
    return field_path


def atool_field_lookup(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index top-level and iterator ATool fields by name."""
    result: dict[str, dict[str, Any]] = {}
    for field in fields:
        name = str(field.get("name", "")).strip()
        if name and name not in result:
            result[name] = field
    return result


def iterator_controls(template: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return authored iterator IDs and their defining type/path."""
    result: dict[str, dict[str, str]] = {}
    for document in template.get("Documents", []):
        for layout in document.get("Layouts", []) if isinstance(document, dict) else []:
            for content in layout.get("Contents", []) if isinstance(layout, dict) else []:
                iteration = content.get("Iteration") if isinstance(content, dict) else None
                if isinstance(iteration, dict) and iteration.get("$$Id"):
                    result.setdefault(str(iteration["$$Id"]), {
                        "type": str(iteration.get("Type", "Iterator")),
                        "path": str(iteration.get("Path", "")),
                    })
    return result


# Comms injects only package pagination and generation-date values. Keep this
# deliberately narrow: an unrecognised blob ID is a mapping defect to surface,
# not a reason to silently call it system-generated.
SYSTEM_GENERATED_FIELDS = {"PackagePageCount", "PackagePageNum", "CurrentDate", "PackageCurrentDate"}


def field_from_content_reference(name: str, field_catalog: dict[str, dict[str, Any]], content_name: str = "", controls: dict[str, dict[str, str]] | None = None, details: str = "") -> dict[str, Any]:
    """Resolve a blob field to ATool's global Field definition when available."""
    defined = field_catalog.get(name)
    if defined:
        path = str(defined.get("path", ""))
        base = str(defined.get("iterator", ""))
        return {"name": name, "path": path, "resolved_path": resolve_iterator_field_path(base, path) if base else path, "iterator": base, "detail": details, "content": content_name}
    control = (controls or {}).get(name)
    if control:
        classification = "AT iterator control"
        details = "; ".join(item for item in (f"Type: {control['type']}" if control.get("type") else "", f"Path: {control['path']}" if control.get("path") else "", details) if item)
    elif name in SYSTEM_GENERATED_FIELDS:
        classification = "System Generated Field"
    else:
        classification = "ERROR: definition not found (AT)"
    return {
        "name": name,
        "path": "",
        "resolved_path": classification,
        "iterator": "", "detail": details,
        "content": content_name,
    }


def document_structure(document: dict[str, Any], content_usage: dict[str, list[str]] | None = None, field_catalog: dict[str, dict[str, Any]] | None = None, controls: dict[str, dict[str, str]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return layout/content structure and all direct/iterator fields for one document."""
    structure, fields = [], []
    for layout in document.get("Layouts", []):
        if not isinstance(layout, dict):
            continue
        layout_name = str(layout.get("$$Id", "(unnamed layout)"))
        contents = []
        for content in layout.get("Contents", []):
            if not isinstance(content, dict):
                continue
            content_name = str(content.get("$$Id", "(unnamed content)"))
            iteration = content.get("Iteration") if isinstance(content.get("Iteration"), dict) else None
            contents.append({"name": content_name, "condition": str(content.get("Condition", "")), "iterator": iteration})
            known_names: set[str] = set()
            for field in content.get("Fields", []):
                if isinstance(field, dict):
                    name = str(field.get("Name", ""))
                    known_names.add(name)
                    fields.append({"name": name, "path": str(field.get("Path", "")), "resolved_path": str(field.get("Path", "")), "iterator": "", "content": content_name})
            if iteration:
                iterator_path = str(iteration.get("Path", ""))
                for field in iteration.get("Fields", []):
                    if isinstance(field, dict):
                        name = str(field.get("Name", ""))
                        known_names.add(name)
                        fields.append({"name": name, "path": str(field.get("Path", "")), "resolved_path": resolve_iterator_field_path(iterator_path, str(field.get("Path", ""))), "iterator": iterator_path, "content": content_name})
            for field_name in (content_usage or {}).get(content_name, []):
                if field_name not in known_names:
                    fields.append(field_from_content_reference(field_name, field_catalog or {}, content_name, controls))
        structure.append({"name": layout_name, "condition": str(layout.get("Condition", "")), "contents": contents})
    return structure, fields


def content_closure(content_names: set[str], content_references: dict[str, list[str]]) -> set[str]:
    """Return contents and the conditional content included from them."""
    resolved = set(content_names)
    pending = list(content_names)
    while pending:
        source = pending.pop()
        for target in content_references.get(source, []):
            if target and target not in resolved:
                resolved.add(target)
                pending.append(target)
    return resolved


def resolved_layout_lines(root_names: list[str], graph: dict[str, Any], content_usage: dict[str, list[str]], iterator_usage: dict[str, list[str]], at_structure: list[dict[str, Any]], content_references: dict[str, list[str]], content_styles: dict[str, list[str]]) -> list[str]:
    nodes = graph.get("nodes", {}) if isinstance(graph, dict) else {}
    by_name = {node.get("name"): node for node in nodes.values() if isinstance(node, dict)}
    at_layouts = {str(layout.get("name", "")): layout for layout in at_structure if layout.get("name")}
    lines: list[str] = []
    def render_content(content_name: str, depth: int, area: str = "", conditional: bool = False, trail: set[str] | None = None) -> None:
        prefix = "  " * depth
        label = f"{prefix}- Content: `{content_name}`"
        if conditional:
            label += " [conditional include]"
        if area:
            label += f" (area: {area})"
        lines.append(label)
        if content_styles.get(content_name):
            lines.append(f"{prefix}  - Styles: {style_links(content_styles[content_name])}")
        iterator_field_names = iterator_usage.get(content_name, [])
        iterator_fields = set(iterator_field_names)
        # Blob parsing reports iterator names as ordinary <comms-data> uses as
        # well.  The Assembly Template has the richer iterator definition, so
        # render that one authoritative entry rather than duplicate it.
        for field_name in dict.fromkeys(content_usage.get(content_name, [])):
            if field_name in iterator_fields:
                continue
            lines.append(f"{prefix}  - Field: [{field_name}](#{field_anchor(field_name)})")
        for field_name in iterator_field_names:
            lines.append(f"{prefix}  - Iterator field: [{field_name}](#{field_anchor(field_name)})")
        next_trail = (trail or set()) | {content_name}
        for target in content_references.get(content_name, []):
            if target in next_trail:
                lines.append(f"{prefix}  - Content: `{target}` [conditional include; cycle stopped]")
            else:
                render_content(target, depth + 1, conditional=True, trail=next_trail)

    def visit(node: dict[str, Any], depth: int, trail: set[str]) -> None:
        prefix = "  " * depth
        identity = str(node.get("uuid", node.get("name", "")))
        if identity in trail:
            lines.append(f"{prefix}- **{node.get('name')}** [{node.get('type')}] — cycle stopped")
            return
        lines.append(f"{prefix}- **{node.get('name')}** [{node.get('type')}]")
        node_styles = referenced_style_names(node.get("styles", []))
        if node_styles:
            lines.append(f"{prefix}  - Styles: {style_links(node_styles)}")
        next_trail = trail | {identity}
        for content in node.get("contents", []):
            content_name = str(content.get("name", ""))
            render_content(content_name, depth + 1, str(content.get("area") or ""))
        # The Assembly Template supplies the semantic placement for conditional
        # and iterator content even where Comms realizes it through a selector
        # or an intermediate layout. Keep those declared children with their
        # authored parent layout instead of flattening them below the graph.
        authored_layout = at_layouts.get(str(node.get("name", "")))
        if authored_layout:
            direct_contents = {str(item.get("name", "")) for item in node.get("contents", [])}
            for content in authored_layout.get("contents", []):
                content_name = str(content.get("name", ""))
                if content_name and content_name not in direct_contents:
                    render_content(content_name, depth + 1)
        for child in node.get("childLayouts", []):
            child_node = nodes.get(child.get("uuid"))
            if child_node:
                visit(child_node, depth + 1, next_trail)
            else:
                lines.append(f"{prefix}  - Layout: **{child.get('name')}** [unresolved]")
    for name in root_names:
        node = by_name.get(name)
        if node:
            visit(node, 0, set())
        else:
            lines.append(f"- **{name}** [unresolved]")
    rendered_layout_names = {str(node.get("name", "")) for node in nodes.values() if isinstance(node, dict)}
    for layout in at_structure:
        layout_name = str(layout.get("name", ""))
        if not layout_name or layout_name in rendered_layout_names:
            continue
        lines.append(f"- **{layout_name}** [Assembly Template layout]")
        for content in layout.get("contents", []):
            render_content(str(content.get("name", "")), 1)
    return lines


def graph_content_names(document: dict[str, Any], graph: dict[str, Any]) -> set[str]:
    nodes = graph.get("nodes", {}) if isinstance(graph, dict) else {}
    names: set[str] = set()
    def visit(uuid: str, trail: set[str]) -> None:
        if not uuid or uuid in trail:
            return
        node = nodes.get(uuid, {})
        names.update(str(item.get("name", "")) for item in node.get("contents", []) if item.get("name"))
        for child in node.get("childLayouts", []):
            visit(str(child.get("uuid", "")), trail | {uuid})
    for root in document.get("roots", []):
        visit(str(root.get("uuid", "")), set())
    return names


def field_anchor(name: str) -> str:
    return "field-" + "".join(char.lower() if char.isalnum() else "-" for char in name).strip("-")


def style_anchor(name: str) -> str:
    return "style-" + "".join(char.lower() if char.isalnum() else "-" for char in name).strip("-")


def load_content_styles(content_root: Path, known_style_names: set[str] | None = None, effective_date: str = "") -> tuple[dict[str, list[str]], dict[str, str]]:
    """Collect configured and inline CSS classes used by each content item."""
    styles: defaultdict[str, list[str]] = defaultdict(list)
    details: dict[str, str] = {}
    for master in content_root.glob("*/*_master.json"):
        try:
            content_name = json.loads(master.read_text(encoding="utf-8")).get("CommunicationContentConfigRec", {}).get("CommunicationContentConfigInfo", {}).get("ShortName", "")
        except (OSError, json.JSONDecodeError):
            continue
        version_files = [path for path in master.parent.glob("versions/*/*.json") if path.stem == path.parent.name]
        if effective_date:
            candidates: list[tuple[str, Path]] = []
            for version in version_files:
                try:
                    payload = json.loads(version.read_text(encoding="utf-8"))
                    status = payload.get("CommunicationContentVersionConfigRec", payload).get("Status", {}).get("Items", [])
                    dates = [str(item.get("EffDtTm", "")) for item in status if item.get("StatusCode") == "Active" and str(item.get("EffDtTm", ""))[:10] <= effective_date]
                    if dates:
                        candidates.append((max(dates), version))
                except (OSError, json.JSONDecodeError):
                    continue
            version_files = [max(candidates, key=lambda item: item[0])[1]] if candidates else []
        for version in version_files:
            try:
                items = json.loads(version.read_text(encoding="utf-8")).get("CommunicationContentVersionConfigInfo", {}).get("CommunicationContentVersionConfigData", {}).get("Items", [])
            except (OSError, json.JSONDecodeError):
                continue
            for item in items:
                for name in item.get("StyleClassName", []) or []:
                    if name and name not in styles[content_name]:
                        styles[content_name].append(str(name))
        blob_files = [blob for version in version_files for blob in version.parent.glob("*.blob")]
        for blob in blob_files:
            try:
                text = html.unescape(blob.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            for classes in re.findall(r"\bclass\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE):
                # Comms style names may contain spaces (for example
                # `ADEC Size`). Prefer that exact configured name before
                # interpreting whitespace as several ordinary CSS classes.
                names = [classes.strip()] if classes.strip() in (known_style_names or set()) else classes.split()
                for name in names:
                    if name.casefold() == "table":
                        continue
                    if name and name not in styles[content_name]:
                        styles[content_name].append(name)
    return dict(styles), details


def load_style_cache(path_text: str | None) -> dict[str, str]:
    """Load detailed style configuration records from an OCCS CLI cache."""
    if not path_text:
        return {}
    root = Path(path_text).expanduser()
    catalog: dict[str, str] = {}
    for path in root.rglob("*.json") if root.exists() else []:
        try:
            info = json.loads(path.read_text(encoding="utf-8")).get("CommunicationStyleConfigRec", {}).get("CommunicationStyleConfigInfo", {})
        except (OSError, json.JSONDecodeError):
            continue
        name = str(info.get("ShortName", ""))
        if not name:
            continue
        attributes = info.get("CommunicationStyleConfigStyleAttribute", {}).get("Items", [])
        detail = "; ".join(
            f"{item.get('StyleAttributeName')}: {item.get('StyleAttributeValue')}"
            for item in attributes if isinstance(item, dict) and item.get("StyleAttributeName")
        ) or str(info.get("Desc", "")) or "No explicit attributes configured."
        catalog[name] = detail
    return catalog


def load_style_catalog(render_evidence: list[dict[str, Any]], inline_details: dict[str, str], cache_path: str | None = None) -> dict[str, str]:
    """Build the style glossary from live Comms metadata and blob CSS evidence."""
    catalog = dict(inline_details)
    for render in render_evidence:
        metadata = render.get("metadata")
        try:
            payload = json.loads(Path(str(metadata)).read_text(encoding="utf-8"))
            styles = payload.get("Styles", [])
        except (OSError, json.JSONDecodeError):
            continue
        for style in styles:
            name = str(style.get("ShortName", ""))
            if not name:
                continue
            attributes = style.get("Attributes", [])
            detail = "; ".join(f"{key}: {value}" for item in attributes if isinstance(item, dict) for key, value in item.items()) or "No explicit attributes returned by Comms."
            catalog.setdefault(name, detail)
        definition = str(payload.get("Package", {}).get("StyleClassDefinition", ""))
        for name, css in re.findall(r"\.([^\s.{]+)\s*\{([^}]*)\}", definition):
            catalog.setdefault(name, css.strip())
    # A downloaded style cache contains the full configured attributes and is
    # more complete than a single render's metadata style list.
    catalog.update(load_style_cache(cache_path))
    return catalog


def load_style_class_catalog(cache_root: Path) -> dict[str, list[str]]:
    """Resolve Comms CSS class names to their configured style short names."""
    uuid_to_name: dict[str, str] = {}
    for path in (cache_root / "styles").rglob("*.json") if (cache_root / "styles").is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8")).get("CommunicationStyleConfigRec", {})
            uuid = str(record.get("CommunicationStyleConfigUuid", ""))
            name = str(record.get("CommunicationStyleConfigInfo", {}).get("ShortName", ""))
            if uuid and name:
                uuid_to_name[uuid] = name
        except (OSError, json.JSONDecodeError):
            continue
    resolved: defaultdict[str, set[str]] = defaultdict(set)
    for folder in ("documents", "layouts", "contents"):
        for path in (cache_root / folder).rglob("*.json") if (cache_root / folder).is_dir() else []:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            def style_name_from(value: object) -> str:
                if not isinstance(value, dict):
                    return ""
                record = value.get("CommunicationStyleConfigRec", value)
                if not isinstance(record, dict):
                    return ""
                return str(record.get("CommunicationStyleConfigInfo", {}).get("ShortName", "")).strip()

            def visit(value: object, inherited_style_name: str = "") -> None:
                if isinstance(value, dict):
                    # Expanded content-version records keep the relationship
                    # and its target style as siblings. Resolve that shape
                    # before descending into either sibling.
                    local_style_name = style_name_from(value) or inherited_style_name
                    for child in value.values():
                        if not isinstance(child, dict):
                            continue
                        for key, relation in child.items():
                            if not key.endswith("RelInfo") or "StyleConfig" not in key or not isinstance(relation, dict):
                                continue
                            class_name = str(relation.get("StyleClassName", "")).strip()
                            uuid = str(relation.get("CommunicationStyleConfigUuid", ""))
                            style_name = local_style_name or style_name_from(child) or uuid_to_name.get(uuid, "")
                            if class_name and style_name:
                                resolved[class_name].add(style_name)
                    for child in value.values():
                        visit(child, local_style_name)
                elif isinstance(value, list):
                    for child in value:
                        visit(child, inherited_style_name)
            visit(payload)
    return {name: sorted(styles, key=str.casefold) for name, styles in resolved.items()}


def style_links(names: list[str]) -> str:
    return ", ".join(f"[{name}](#{style_anchor(name)})" for name in names if name)


def referenced_style_names(style_refs: list[dict[str, Any]]) -> list[str]:
    """Expose both the configured style and CSS class applied to an element."""
    names: list[str] = []
    for item in style_refs:
        if not isinstance(item, dict):
            continue
        for name in (str(item.get("name", "")), str(item.get("className", ""))):
            if name and name not in names:
                names.append(name)
    return names


def heading_anchor(text: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in text).strip("-")


def values_for_path(payload: object, path: str) -> list[object]:
    """Resolve an authored JSONPath using the same path evaluator as ATool."""
    if not path or path.startswith("("):
        return []
    try:
        return ConditionEvaluator()._extract_values_by_path(payload, path)
    except (AttributeError, TypeError, ValueError):
        return []


def values_differ(baseline: object, candidate: object, path: str) -> bool:
    def stable(values: list[object]) -> list[str]:
        return [json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) for value in values]
    return stable(values_for_path(baseline, path)) != stable(values_for_path(candidate, path))


def load_blob_conditions(content_root: Path) -> dict[str, list[str]]:
    """Read conditional expressions authored inside downloaded content blobs."""
    result: defaultdict[str, list[str]] = defaultdict(list)
    for master in content_root.glob("*/*_master.json"):
        try:
            content_name = json.loads(master.read_text(encoding="utf-8")).get("CommunicationContentConfigRec", {}).get("CommunicationContentConfigInfo", {}).get("ShortName", "")
        except (OSError, json.JSONDecodeError):
            continue
        for blob in master.parent.glob("versions/**/*.blob"):
            try:
                text = html.unescape(blob.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            for raw in re.findall(r"<comms-cond>\s*\$Cond([\s\S]*?)</comms-cond>", text, flags=re.IGNORECASE):
                try:
                    condition = json.loads(raw.strip()).get("Condition", "")
                except json.JSONDecodeError:
                    condition = ""
                if condition and condition not in result[content_name]:
                    result[content_name].append(str(condition))
    return dict(result)


def document_conditions(document: dict[str, Any], structure: list[dict[str, Any]], content_references: dict[str, list[str]], blob_conditions: dict[str, list[str]]) -> list[str]:
    """Gather the authored conditions which can alter this document's output."""
    conditions = [str(document.get("Condition", ""))]
    contents: set[str] = set()
    for layout in structure:
        if layout.get("condition"):
            conditions.append(str(layout["condition"]))
        for content in layout.get("contents", []):
            contents.add(str(content.get("name", "")))
            if content.get("condition"):
                conditions.append(str(content["condition"]))
    for content_name in content_closure(contents, content_references):
        conditions.extend(blob_conditions.get(content_name, []))
    return list(dict.fromkeys(item for condition in conditions for item in condition_atoms(condition) if item))


def describe_condition(condition: str, clauses: list[dict[str, Any]]) -> str:
    compact = "".join(condition.split())
    for clause in clauses:
        if compact == "".join(str(clause.get("expression", "")).split()):
            description = f" — {clause['description']}" if clause.get("description") else ""
            return f"`{clause['name']}`{description}"
    return f"`{condition}`"


def scenario_delta_lines(
    document_id: str,
    conditions: list[str],
    clauses: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    evaluator: AToolConditionEvaluator,
) -> list[str]:
    """Describe only the changes relevant to this document versus its baseline."""
    if not baseline:
        return ["- Baseline input was not available; no scenario delta could be calculated."]
    baseline_payload = baseline["payload_data"]
    baseline_present = document_id in baseline["rendered_documents"]
    baseline_atoms = {atom: evaluator._evaluator._evaluate_condition_expression(atom, baseline_payload) for atom in conditions}
    lines: list[str] = []
    for candidate in candidates:
        if candidate["payload"] == baseline["payload"]:
            continue
        candidate_present = document_id in candidate["rendered_documents"]
        changed_clauses = [
            f"{describe_condition(atom, clauses)} ({'true' if baseline_atoms[atom] else 'false'} → {'true' if evaluator._evaluator._evaluate_condition_expression(atom, candidate['payload_data']) else 'false'})"
            for atom in baseline_atoms
            if baseline_atoms[atom] != evaluator._evaluator._evaluate_condition_expression(atom, candidate["payload_data"])
        ]
        if not baseline_present and not candidate_present:
            continue
        label = f" — {candidate['label']}" if candidate.get("label") else ""
        heading = f"- **{candidate['scenario']}**{label}"
        if baseline_present and candidate_present:
            if changed_clauses:
                lines.append(f"{heading}: renders this document.")
            else:
                lines.append(f"{heading}: renders the same document; no detected differences.")
        elif candidate_present:
            lines.append(f"{heading}: renders this document, which is not present in the baseline.")
        else:
            lines.append(f"{heading}: does not render this document.")
        if changed_clauses:
            lines.append("  - Trigger clauses: " + "; ".join(changed_clauses[:8]) + ("; …" if len(changed_clauses) > 8 else ""))
    return lines or ["- No variants configured for this document."]


def file_updated_at(path_text: str | None) -> str:
    """Return a stable, user-facing file cache timestamp when available."""
    if not path_text:
        return "unknown"
    try:
        return datetime.fromtimestamp(Path(path_text).stat().st_mtime, UTC).strftime('%Y-%m-%d %H:%M UTC')
    except OSError:
        return "unknown"


def display_timestamp(value: str | None) -> str:
    """Render OCCS manifest timestamps and file timestamps consistently."""
    if not value:
        return "unknown"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')
    except ValueError:
        return value


def comms_cache_pulled_at(source: dict[str, Any]) -> str:
    """Use OCCS' manifest `createdAt`, the precise package-get completion time."""
    manifest = source.get("manifest")
    if isinstance(manifest, dict) and manifest.get("createdAt"):
        return display_timestamp(str(manifest["createdAt"]))
    if source.get("cachedAt"):
        return display_timestamp(str(source["cachedAt"]))
    snapshot = source.get("snapshot")
    if snapshot:
        try:
            manifest = json.loads((Path(str(snapshot)) / "occs-package.json").read_text(encoding="utf-8"))
            if isinstance(manifest, dict) and manifest.get("createdAt"):
                return display_timestamp(str(manifest["createdAt"]))
        except (OSError, json.JSONDecodeError):
            pass
    return "unknown"


def generate(profile_path: Path, output_path: Path, source_mode: str = "comms", render_evidence_mode: str = "metadata", workers: int = 3, formats: set[str] | None = None, xml_conversion: str = "auto", rebuild_resource_index: bool = False) -> None:
    formats = formats or {"md"}
    unsupported = formats - {"md", "docx", "pdf"}
    if unsupported:
        raise ValueError(f"Unsupported output formats: {', '.join(sorted(unsupported))}")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    occs = profile.get("occs", {})
    if source_mode == "comms":
        template, package_associations, source = fetch_live_bundle(profile.get("comms", {}), occs, output_path.parent / "configuration-snapshot")
        template_path = Path(source["snapshot"]) / "assembly-template.json"
    elif source_mode == "cached":
        template, resource_cache, source = load_resource_cache(profile.get("comms", {}))
        template_path = Path(source["packageCache"]) / "AssemblyTemplate.json"
        package_associations = []
    else:
        template_path = Path(profile["template"]).expanduser()
        if not template_path.is_absolute():
            template_path = (profile_path.parent / template_path).resolve()
        template = json.loads(template_path.read_text(encoding="utf-8"))
        package_associations = []
        source = {"mode": "saved-template", "template": str(template_path)}
    observations: list[dict[str, Any]] = []
    render_evidence: list[dict[str, Any]] = []
    scenario_root = profile.get("scenarios")
    if not isinstance(scenario_root, str) or not scenario_root.strip():
        raise ValueError("Profile scenarios must be the folder containing scenario subfolders")
    scenarios = discover_scenarios(scenario_root, profile_path)
    baseline_specs = declared_baselines(profile, scenarios)
    # A declared baseline plan is intentionally selective: only the inputs
    # named by a document baseline or one of its variants are rendered.
    selected_inputs = {
        (item["scenario"], item["input"])
        for baseline in baseline_specs
        for item in ([baseline] + baseline["variants"])
    }
    resource_cache_root = Path(str(source.get("resourceCache", output_path.parent / "scoped-content-catalog")))
    resource_content_root = resource_cache_root / "contents"
    cached_style_names = set(load_style_cache(str(resource_cache_root / "styles"))) if source_mode == "cached" else set()
    content_usage_path = output_path.parent / "resource-cache-index" / "content-usage.json" if source_mode == "cached" else resource_content_root / "content-usage.json"
    if source_mode == "cached" and rebuild_resource_index:
        index_dir = content_usage_path.parent
        if index_dir.exists():
            shutil.rmtree(index_dir)
    if source_mode == "cached" and not content_usage_path.exists():
        script = Path(__file__).with_name("build_content_catalog.mjs")
        result = subprocess.run(["node", str(script), str(resource_content_root), str(content_usage_path.parent), str(profile.get("comms", {}).get("effective_date", "9999-12-31"))], capture_output=True, text=True, timeout=300)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().replace("\n", " ")
            raise ValueError(f"Resource-cache content catalog build failed: {detail or f'exit code {result.returncode}'}")
    if not content_usage_path.exists():
        content_usage_path = output_path.parent / "scoped-content-catalog" / "content-usage.json"
    try:
        content_usage = json.loads(content_usage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        content_usage = {}
    try:
        content_references = json.loads((content_usage_path.parent / "content-references.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        content_references = {}
    try:
        content_field_details = json.loads((content_usage_path.parent / "content-field-details.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        content_field_details = {}
    try:
        content_style_classes = json.loads((content_usage_path.parent / "content-style-classes.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        content_style_classes = {}
    blob_conditions = load_blob_conditions(content_usage_path.parent)
    content_styles, inline_style_details = load_content_styles(resource_content_root if source_mode == "cached" else content_usage_path.parent, cached_style_names, str(profile.get("comms", {}).get("effective_date", "")) if source_mode == "cached" else "")
    try:
        layout_graph = json.loads((output_path.parent / "layout-graph.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        layout_graph = {}

    # Phase 1: XML conversion is deliberately serialized. The OCCS converter
    # refreshes the saved session token, so concurrent conversions contend.
    jobs: list[tuple[str, Path, Path]] = []
    conversion_errors: list[dict[str, Any]] = []
    for scenario in scenarios:
        for input_file in scenario["inputs"]:
            if baseline_specs and (scenario["name"], input_file.name) not in selected_inputs:
                continue
            try:
                # ATool users commonly keep its validated JSON conversion
                # alongside an XML source. Prefer that exact sibling over a
                # second conversion: it is the reviewed preview input and
                # avoids two jobs writing the same metadata evidence name.
                sibling_json = input_file.with_suffix(".json")
                payloads = ([sibling_json] if input_file.suffix.lower() == ".xml" and sibling_json.is_file() else
                            convert_xml_to_files(input_file, occs, output_path.parent / "converted-inputs" / scenario["name"], xml_conversion)
                            if input_file.suffix.lower() == ".xml" else [input_file])
                jobs.extend((scenario["name"], input_file, payload) for payload in payloads)
            except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                conversion_errors.append({"scenario": scenario["name"], "file": input_file, "error": str(error)})
    observations.extend(conversion_errors)

    # Phase 2: all previews use JSON, so the refreshed session can be used by
    # bounded concurrent Comms metadata requests without XML converter churn.
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(process_input, name, source_input, payload, template, profile, output_path, render_evidence_mode) for name, source_input, payload in jobs]
        for future in as_completed(futures):
            input_observations, input_renders = future.result()
            observations.extend(input_observations)
            render_evidence.extend(input_renders)

    observed: dict[str, dict[str, Any]] = {}
    sources: defaultdict[str, set[str]] = defaultdict(set)
    for observation in observations:
        for document in observation.get("documents", []):
            observed.setdefault(document["id"], document)
            label = f"{observation['scenario']} / {observation['file'].name}"
            if observation.get("transaction"):
                label += f" (transaction {observation['transaction']})"
            sources[document["id"]].add(label)

    # Comms metadata decides document presence. ATool's local result is used
    # only as a fallback when an older cached metadata run has no record.
    rendered_by_payload: defaultdict[str, set[str]] = defaultdict(set)
    rendered_order_by_payload: dict[str, list[str]] = {}
    metadata_payloads: set[str] = set()
    for render in render_evidence:
        payload_key = str(render.get("payload", ""))
        if render.get("metadata") and "error" not in render:
            metadata_payloads.add(payload_key)
            rendered_order_by_payload.setdefault(payload_key, [str(item) for item in render.get("documents", [])])
        if render.get("documents"):
            rendered_by_payload[payload_key].update(str(item) for item in render["documents"])
    local_by_payload: defaultdict[str, set[str]] = defaultdict(set)
    for observation in observations:
        local_by_payload[str(observation.get("payload", ""))].update(str(item["id"]) for item in observation.get("documents", []))
    scenario_candidates: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    # Metadata is still valid evidence even if ATool's diagnostic evaluation
    # of that same input raises an exception. Build candidates from the planned
    # payload jobs rather than excluding them with local-observation errors.
    for scenario_name, source_input, payload_path in jobs:
        try:
            payload_data = load_sample(payload_path)
        except (OSError, json.JSONDecodeError):
            continue
        payload_key = str(payload_path)
        scenario_candidates[str(scenario_name)].append({
            "scenario": str(scenario_name), "file": source_input,
            "payload": payload_key, "payload_data": payload_data,
            "rendered_documents": rendered_by_payload.get(payload_key) or local_by_payload.get(payload_key, set()),
            "rendered_document_order": rendered_order_by_payload.get(payload_key, []),
        })
    def candidate_for(scenario_name: str, input_name: str) -> dict[str, Any] | None:
        options = [
            item for item in scenario_candidates.get(scenario_name, [])
            if item["file"].name == input_name and item["payload"] in metadata_payloads
        ]
        return sorted(options, key=lambda item: item["payload"].casefold())[0] if options else None

    # A profile baseline plan is the TD's explicit scope and order. Each
    # baseline is independently verified against Comms metadata, rather than
    # inferring family members from a single representative bill.
    document_plans: list[dict[str, Any]] = []
    if baseline_specs:
        for spec in baseline_specs:
            baseline = candidate_for(spec["scenario"], spec["input"])
            if baseline is None:
                raise ValueError(f"Baseline Comms METADATA was not available for {spec['document']}: {spec['scenario']} / {spec['input']}.")
            if spec["document"] not in baseline["rendered_documents"]:
                rendered = ", ".join(baseline["rendered_document_order"]) or "no documents"
                raise ValueError(f"Baseline {spec['document']} did not render for {spec['scenario']} / {spec['input']}. Comms returned: {rendered}.")
            variants: list[dict[str, Any]] = []
            for variant in spec["variants"]:
                candidate = candidate_for(variant["scenario"], variant["input"])
                if candidate is None:
                    raise ValueError(f"Variant Comms METADATA was not available for {spec['document']}: {variant['scenario']} / {variant['input']}.")
                variants.append({**candidate, "label": variant.get("label", "")})
            document_plans.append({"spec": spec, "baseline": baseline, "variants": variants})
        baseline_documents = [item["spec"]["document"] for item in document_plans]
        source["baselineMetadata"] = [
            {"document": item["spec"]["document"], "scenario": item["baseline"]["scenario"], "input": item["baseline"]["file"].name,
             "renderedDocuments": item["baseline"]["rendered_document_order"]}
            for item in document_plans
        ]
    else:
        # Legacy single-baseline behaviour remains available for existing
        # profiles, but new profiles should use the explicit baselines list.
        representatives = [
            sorted(items, key=lambda item: (str(item["file"]).casefold(), item["payload"].casefold()))[0]
            for items in scenario_candidates.values() if items
        ]
        baseline_name = str(profile.get("baseline_scenario", "Regular (Cyclic)"))
        baseline_input = str(profile.get("baseline_input", "")).strip()
        baseline_options = [
            item for item in scenario_candidates.get(baseline_name, [])
            if item["payload"] in metadata_payloads and (not baseline_input or item["file"].name == baseline_input)
        ]
        if not baseline_input and len(baseline_options) > 1:
            raise ValueError(f"Baseline scenario {baseline_name} has {len(baseline_options)} successful Comms METADATA inputs. Set baseline_input to the single reference case to use.")
        baseline = sorted(baseline_options, key=lambda item: (str(item["file"]).casefold(), item["payload"].casefold()))[0] if baseline_options else None
        if baseline is None:
            requested = f" / {baseline_input}" if baseline_input else ""
            raise ValueError(f"Baseline Comms METADATA is required but was not available for {baseline_name}{requested}.")
        baseline_documents = baseline["rendered_document_order"]
        if not baseline_documents:
            raise ValueError(f"Baseline Comms METADATA returned no rendered documents for {baseline_name} / {baseline['file'].name}.")
        document_plans = [{"spec": {"document": document, "label": "", "scenario": baseline_name, "input": baseline["file"].name, "variants": []}, "baseline": baseline, "variants": representatives} for document in baseline_documents]
        source["baselineMetadata"] = {"scenario": baseline_name, "input": baseline["file"].name, "documents": baseline_documents}
    if source_mode == "comms":
        refresh_document_graph(source, output_path.parent, baseline_documents)
        try:
            document_graph = json.loads((output_path.parent / "document-graph.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            document_graph = {}
    elif source_mode == "cached":
        document_graph = resource_document_graph(resource_cache_root, baseline_documents, str(profile.get("comms", {}).get("effective_date", "9999-12-31")))
    else:
        document_graph = {}
    if source_mode == "comms":
        refresh_content_catalog(output_path.parent, document_graph, baseline_documents)
        # The baseline live graph has just established the exact content scope;
        # rebuild the blob-derived data from that scope rather than retaining a
        # broader cache from a prior report run.
        try:
            content_usage = json.loads(content_usage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            content_usage = {}
        try:
            content_references = json.loads((content_usage_path.parent / "content-references.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            content_references = {}
        blob_conditions = load_blob_conditions(content_usage_path.parent)
        content_styles, inline_style_details = load_content_styles(content_usage_path.parent)

    fields = normalise_fields(template)
    clauses, clause_source = load_atool_clauses(profile, source)
    if clause_source:
        source["atoolMetadata"] = clause_source
    evidence = TechnicalDesignEvidence(
        family=str(profile.get("family", "Unnamed document family")),
        source=source,
        observed_documents=observed,
        package_associations=package_associations,
        fields=fields,
        clauses=clauses,
        render_evidence=render_evidence,
    )
    evidence.scenarios = [
        ScenarioEvidence(
            name=scenario["name"], folder=str(scenario["folder"]), inputs_discovered=len(scenario["inputs"]),
            transactions_evaluated=sum(1 for item in observations if item["scenario"] == scenario["name"] and "documents" in item),
        )
        for scenario in scenarios
    ]
    evidence.exceptions = [
        {"scenario": item["scenario"], "input": str(item["file"]), "message": item["error"]}
        for item in observations if "error" in item
    ]

    # The explicit profile baseline list controls report scope and order. The
    # Assembly Template contributes conditions, iterator definitions, and
    # field semantics; cached Comms resources provide actual structure.
    template_documents = {
        str(item.get("$$Id", "")): item for item in template.get("Documents", [])
        if isinstance(item, dict) and item.get("$$Id")
    }
    scoped = [
        {**template_documents.get(plan["spec"]["document"], {"$$Id": plan["spec"]["document"], "Condition": "", "Layouts": []}), "_plan": plan}
        for plan in document_plans
    ]
    document_heading_text = {
        str(document["$$Id"]): str(document["$$Id"]) + (
            f" — {description}" if (description := str(document_graph.get("documents", {}).get(str(document["$$Id"]), {}).get("description") or document.get("Descr") or "").strip()) else ""
        )
        for document in scoped
    }
    generated_on = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    lines = [f"# Technical Design: {profile.get('family', 'Unnamed document family')}", "", "## Contents", "", "- [Scope](#scope)", "- [Documents](#documents)"]
    lines.extend(f"  - [{item.get('$$Id')}](#{heading_anchor(str(item.get('$$Id')))})" for item in scoped)
    style_catalog = load_style_catalog(render_evidence, inline_style_details, str(resource_cache_root / "styles") if (resource_cache_root / "styles").is_dir() else None)
    style_classes = load_style_class_catalog(resource_cache_root) if source_mode == "cached" else {}
    style_classes_by_case = {name.casefold(): targets for name, targets in style_classes.items()}
    style_catalog_by_case = {name.casefold(): detail for name, detail in style_catalog.items()}
    lines.extend(["- [Glossary](#glossary)", "  - [Field List](#field-list)", "  - [Style List](#style-list)", "", "## Scope", "", profile.get("description", ""), "", "### Family member documents", ""])
    for item in scoped:
        spec = item["_plan"]["spec"]
        label = f" — {spec['label']}" if spec.get("label") else ""
        lines.append(f"- `{spec['document']}`{label}")
    lines.extend(["", "### Baseline and variant test cases", ""])
    for item in scoped:
        spec = item["_plan"]["spec"]
        label = f" — {spec['label']}" if spec.get("label") else ""
        lines.append(f"- **{spec['document']}{label}**")
        lines.append(f"  - **Baseline — {spec['scenario']}**: `{spec['input']}`")
        for variant in spec.get("variants", []):
            variant_label = f" — {variant['label']}" if variant.get("label") else ""
            lines.append(f"  - Variant — {variant['scenario']}{variant_label}: `{variant['input']}`")
    lines.extend(["", "## Documents", ""])
    glossary: list[dict[str, Any]] = []
    used_styles: set[str] = set()
    field_catalog = atool_field_lookup(fields)
    atool_iterator_controls = iterator_controls(template)
    for document in scoped:
        document_id = str(document.get("$$Id"))
        document_plan = document["_plan"]
        document_baseline = document_plan["baseline"]
        document_variants = document_plan["variants"]
        structure, document_fields = document_structure(document, content_usage, field_catalog, atool_iterator_controls)
        live_document = document_graph.get("documents", {}).get(document_id, {})
        at_content_names = {str(content.get("name", "")) for layout in structure for content in layout.get("contents", []) if content.get("name")}
        actual_content_names = graph_content_names(live_document, document_graph) | at_content_names
        actual_content_fields = sorted({field for content in content_closure(actual_content_names, content_references) for field in content_usage.get(content, [])})
        known_field_names = {field["name"] for field in document_fields}
        document_fields.extend(
            field_from_content_reference(
                field_name, field_catalog, content, atool_iterator_controls,
                "; ".join(content_field_details.get(content, {}).get(field_name, [])),
            )
            for content in content_closure(actual_content_names, content_references)
            for field_name in content_usage.get(content, [])
            if field_name not in known_field_names
        )
        glossary.extend([{**field, "document": document_id} for field in document_fields])
        title = f"### {document_heading_text[document_id]}"
        lines.extend([f'<a id="{heading_anchor(document_id)}"></a>', title, ""])
        document_styles = referenced_style_names(live_document.get("styles", []))
        if document_styles:
            used_styles.update(document_styles)
            lines.extend(["#### Styles", "", f"{style_links(document_styles)}", ""])
        lines.extend(["#### Triggers", ""])
        matches = clause_matches(str(document.get("Condition", "")), clauses)
        if matches:
            lines.append("ATool clauses represented in the trigger:")
            lines.extend(f"- `{item['name']}` — {item['description']}" for item in matches)
        lines.extend(["", "Constituent expressions:"])
        lines.extend(f"- `{escape(atom)}`" for atom in condition_atoms(str(document.get("Condition", ""))))
        lines.extend(["", "Bare condition JSONPath:", "", f"```text\n{document.get('Condition', '')}\n```", "", "#### Structure", ""])
        graph_for_document = {"nodes": document_graph.get("nodes", {})} if live_document else layout_graph
        root_names = [item.get("name", "") for item in live_document.get("roots", [])] if live_document else [item['name'] for item in structure]
        iterator_usage: defaultdict[str, list[str]] = defaultdict(list)
        for field in document_fields:
            if field.get("iterator"):
                iterator_usage[str(field.get("content", ""))].append(str(field["name"]))
        lines.extend(resolved_layout_lines(root_names, graph_for_document, content_usage, iterator_usage, structure, content_references, content_styles))
        used_styles.update(style for content in content_closure(actual_content_names, content_references) for style in content_styles.get(content, []))
        for node in graph_for_document.get("nodes", {}).values():
            if isinstance(node, dict):
                used_styles.update(referenced_style_names(node.get("styles", [])))
        lines.extend(["", "#### Scenarios", ""])
        baseline_label = f"`{document_baseline['file'].name}`"
        lines.append(f"Compared with **{document_baseline['scenario']}** baseline input {baseline_label}.")
        conditions = document_conditions(document, structure, content_references, blob_conditions)
        lines.extend(scenario_delta_lines(document_id, conditions, clauses, document_baseline, document_variants, AToolConditionEvaluator()))
        lines.append("")
    lines.extend(["## Glossary", "", "### Field list", "", "| Field | Mapping / resolved path | Details | Used by |", "|---|---|---|---|"])
    consolidated_fields: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for field in glossary:
        # A field may appear in several documents. Keep one glossary definition
        # per resolved mapping/iterator and aggregate its usages for lookup.
        key = (str(field["name"]), str(field["resolved_path"]), str(field["iterator"]), str(field.get("detail", "")))
        entry = consolidated_fields.setdefault(key, {**field, "documents": set()})
        entry["documents"].add(str(field["document"]))
    for field in sorted(consolidated_fields.values(), key=lambda item: (str(item["name"]).casefold(), str(item["resolved_path"]))):
        documents = ", ".join(sorted(field["documents"], key=str.casefold))
        details = "; ".join(item for item in (str(field.get("iterator", "")), str(field.get("detail", ""))) if item)
        lines.append(f"| <a id=\"{field_anchor(field['name'])}\"></a>{escape(field['name'])} | `{escape(field['resolved_path'])}` | {escape(details, escape_dollar=True)} | {escape(documents)} |")
    if not glossary:
        lines.append("| _No document fields_ | — | — | — |")
    lines.extend(["", "### Style list", "", "| Style | Details |", "|---|---|"])
    for style in sorted((item for item in used_styles if item), key=str.casefold):
        if style.casefold() in {"style-default", "default"}:
            detail = "System default style"
        elif style.casefold() == "table":
            detail = "HTML table element class"
        elif style.casefold() in style_classes_by_case:
            targets = style_classes_by_case[style.casefold()]
            target_details = "; ".join(f"{target}: {style_catalog.get(target, style_catalog_by_case.get(target.casefold(), 'ERROR: reference not found (output)'))}" for target in targets)
            detail = f"Style class for {', '.join(targets)}. {target_details}"
        elif style in content_style_classes:
            owners = content_style_classes[style]
            target_styles = [owner for owner in owners if owner in style_catalog]
            if target_styles:
                target_details = "; ".join(f"{target}: {style_catalog[target]}" for target in target_styles)
                detail = f"Style class applied by content {', '.join(owners)}. {target_details}"
            else:
                detail = f"Style class applied by content {', '.join(owners)}; associated style was not present in the cache."
        else:
            detail = style_catalog.get(style, style_catalog_by_case.get(style.casefold(), "ERROR: reference not found (output)"))
        lines.append(f"| <a id=\"{style_anchor(style)}\"></a>{escape(style)} | {escape(detail, escape_dollar=True)} |")
    if not used_styles:
        lines.append("| _No styles referenced_ | — |")

    for item in (observation for observation in observations if "error" in observation):
        print(f"Execution exception: {item['scenario']} / {item['file'].name}: {item['error']}", file=sys.stderr)
    comms_snapshot = str(source.get("resourceCache") or source.get("snapshot", ""))
    comms_cached_at = comms_cache_pulled_at(source)
    package_cached_at = file_updated_at(clause_source)
    lines.extend([
        "",
        f"*Comms Source Cached: `{comms_snapshot or source.get('mode', 'unknown')}` — OCCS CLI pull: {comms_cached_at}.*",
        f"*Package Source: `{clause_source or 'not available'}` Cached: {package_cached_at}.*",
        f"*Generated on {generated_on}.*",
    ])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output_path.with_suffix(".evidence.json").write_text(json.dumps(evidence.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if formats & {"docx", "pdf"}:
        renderer = Path(__file__).with_name("render_td.py")
        command = [sys.executable, str(renderer), "--markdown", str(output_path), "--docx", str(output_path.with_suffix(".docx"))]
        if "pdf" in formats:
            command.extend(["--pdf", str(output_path.with_suffix(".pdf"))])
        subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an execution-derived TD using ATool evaluation.")
    commands = parser.add_subparsers(dest="command", required=True)
    generate_command = commands.add_parser("generate")
    generate_command.add_argument("--profile", required=True, type=Path)
    generate_command.add_argument("--out", required=True, type=Path)
    generate_command.add_argument("--source", choices=("comms", "cached", "saved"), default="comms")
    generate_command.add_argument("--render-evidence", choices=("metadata", "cached", "none"), default="metadata")
    generate_command.add_argument("--workers", type=int, default=3, help="Maximum concurrent JSON metadata previews after serialized XML conversion (default: 3).")
    generate_command.add_argument("--xml-conversion", choices=("auto", "always", "never"), default="auto", help="XML input handling: reuse cached conversion, refresh it, or require it (default: auto).")
    generate_command.add_argument("--rebuild-resource-index", action="store_true", help="Rebuild the derived content-field/reference index from the configured Comms resource cache.")
    generate_command.add_argument("--formats", default="md", help="Comma-separated outputs: md, docx, pdf (default: md).")
    args = parser.parse_args()
    formats = {item.strip().lower() for item in args.formats.split(",") if item.strip()}
    generate(args.profile, args.out, args.source, args.render_evidence, args.workers, formats, args.xml_conversion, args.rebuild_resource_index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
