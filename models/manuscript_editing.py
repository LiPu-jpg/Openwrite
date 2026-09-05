"""Strict manuscript version and annotation contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ManuscriptVersionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    version_id: str = Field(pattern=r"^ver_[A-Za-z0-9_-]{8,80}$")
    chapter_id: str = Field(pattern=r"^ch_\d+$")
    source_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: Literal["autosave", "manual", "ai_revision", "full_rewrite", "restore"]
    label: str = Field(default="", max_length=200)
    created_at: str
    content_file: str = Field(
        pattern=r"^data/manuscript_versions/ch_\d+/ver_[A-Za-z0-9_-]{8,80}\.md$"
    )
    writing_units: int = 0


class ManuscriptAnnotationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    annotation_id: str = Field(pattern=r"^ann_[A-Za-z0-9_-]{8,80}$")
    chapter_id: str = Field(pattern=r"^ch_\d+$")
    source_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    quote: str = Field(min_length=1, max_length=4000)
    start_hint: int = Field(ge=0)
    end_hint: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=10000)
    status: Literal["open", "resolved"] = "open"
    anchor_state: Literal["attached", "relocated", "detached"] = "attached"
    current_start: int | None = None
    current_end: int | None = None
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validate_ranges(self) -> ManuscriptAnnotationV1:
        if self.end_hint < self.start_hint:
            raise ValueError("end_hint must not precede start_hint")
        current = (self.current_start, self.current_end)
        if (current[0] is None) != (current[1] is None):
            raise ValueError("current anchor must contain both offsets or neither")
        if current[0] is not None and current[1] is not None and current[1] < current[0]:
            raise ValueError("current_end must not precede current_start")
        if self.anchor_state == "detached" and current != (None, None):
            raise ValueError("detached annotations cannot retain current offsets")
        return self
