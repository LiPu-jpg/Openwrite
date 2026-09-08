"""Strict rolling-plan and runtime-diagnostic contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    item: str
    value: Any = None


class DiagnosticActionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)


class RuntimeDiagnosticFindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    code: str
    severity: Literal["info", "warning", "error", "blocker"]
    summary: str
    explanation: str
    affected_items: tuple[str, ...] = ()
    evidence: tuple[DiagnosticEvidenceV1, ...]
    action: DiagnosticActionV1


class RuntimeDiagnosticReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    report_id: str
    novel_id: str
    generated_at: str
    revision: str
    redacted: Literal[True] = True
    sources: tuple[str, ...]
    findings: tuple[RuntimeDiagnosticFindingV1, ...]


class RollingPlanCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    candidate_id: str
    novel_id: str
    current_arc: str
    created_at: str
    outline_revision: str
    facts_revision: str
    current_window: tuple[str, ...]
    next_window: tuple[str, ...]
    window_size: int = 50
    direction: str
    arc_summary: str
    character_state: tuple[str, ...] = ()
    relationship_state: tuple[str, ...] = ()
    resolved_foreshadowing: tuple[str, ...] = ()
    unresolved_foreshadowing: tuple[str, ...] = ()
    style_drift: tuple[str, ...] = ()
    next_arc_goals: tuple[str, ...] = ()
    state: Literal["candidate", "proposed", "stale"] = "candidate"
    proposal_revision: str = ""

