"""Strict Chapter Run V2 and intervention contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChapterRunV2Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "running", "completed", "failed", "stale", "skipped"] = "pending"
    input_revisions: dict[str, str] = Field(default_factory=dict)
    output_revision: str = ""
    artifact: str = ""
    prompt_version: str = ""
    model_profile: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    attempts: int = Field(default=0, ge=0)
    started_at: str = ""
    completed_at: str = ""


class InterventionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intervention_id: str
    scope: Literal["project", "arc", "chapter", "asset"]
    risk: Literal["low", "medium", "high", "blocker"]
    affected_items: tuple[str, ...] = ()
    rewrite_required: bool = False
    request: str = Field(min_length=1, max_length=10000)
    facts_revision: str = ""
    impact: tuple[str, ...] = ()
    proposal: str = ""
    state: Literal[
        "recorded",
        "facts_read",
        "classified",
        "proposed",
        "awaiting_confirmation",
        "confirmed",
        "applied",
        "rejected",
        "stale",
    ] = "recorded"
    created_at: str
    updated_at: str
    stale_reason: str = ""


class ChapterRunV2Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    run_id: str
    novel_id: str
    chapter_id: str
    status: Literal["running", "drafted", "committed", "reviewed", "failed", "cancelled"] = (
        "running"
    )
    created_at: str
    updated_at: str
    requested_target_words: int = 0
    effective_target_words: int = 0
    provider: str = ""
    model: str = ""
    model_profile: str = ""
    input_revisions: dict[str, str] = Field(default_factory=dict)
    stages: dict[str, ChapterRunV2Stage] = Field(default_factory=dict)
    interventions: tuple[InterventionV1, ...] = ()
    stop_reason: str = ""
    cancel_requested: bool = False
    archived: bool = False
    requested_model: str = ""
    target_words_source: str = ""
