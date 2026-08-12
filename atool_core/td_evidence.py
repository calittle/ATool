"""Stable, machine-readable evidence produced by TD generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ScenarioEvidence:
    name: str
    folder: str
    inputs_discovered: int
    transactions_evaluated: int


@dataclass
class TechnicalDesignEvidence:
    family: str
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: dict[str, Any] = field(default_factory=dict)
    observed_documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    scenarios: list[ScenarioEvidence] = field(default_factory=list)
    package_associations: list[dict[str, Any]] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    clauses: list[dict[str, Any]] = field(default_factory=list)
    render_evidence: list[dict[str, Any]] = field(default_factory=list)
    exceptions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
