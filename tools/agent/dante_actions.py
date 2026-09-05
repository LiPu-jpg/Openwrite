"""High-level Dante action adapter."""

from __future__ import annotations

from typing import Any

from .orchestrator import OpenWriteOrchestrator, OrchestratorResult

OUTLINE_DRAFT_MAX_CHARS = 1200


class DanteActionAdapter:
    def __init__(self, orchestrator: OpenWriteOrchestrator):
        self.orchestrator = orchestrator

    def summarize_ideation(self) -> dict[str, Any]:
        return self._wrap("summarize_ideation", self.orchestrator.summarize_ideation())

    def confirm_ideation_summary(self, text: str = "这个汇总可以") -> dict[str, Any]:
        return self._wrap(
            "confirm_ideation_summary",
            self.orchestrator.confirm_ideation_summary(text),
        )

    def generate_outline_draft(self, request_text: str) -> dict[str, Any]:
        payload = self._wrap(
            "generate_outline_draft",
            self.orchestrator.generate_outline_draft(request_text),
        )
        if payload.get("ok", True) and not payload.get("blocked", False):
            planning_store = getattr(self.orchestrator, "story_planning_store", None)
            if planning_store is not None and hasattr(planning_store, "read_outline_draft"):
                payload["outline_draft"] = planning_store.read_outline_draft(
                    max_chars=OUTLINE_DRAFT_MAX_CHARS
                )
        return payload

    def confirm_outline_scope(self) -> dict[str, Any]:
        return self._wrap(
            "confirm_outline_scope",
            self.orchestrator.confirm_outline_scope(),
        )

    def run_chapter_preflight(self, chapter_id: str) -> dict[str, Any]:
        state_store = getattr(self.orchestrator, "state_store", None)
        if state_store is not None:
            state = state_store.load_or_create()
            if getattr(state, "pending_confirmation", "") == "outline_scope":
                return {
                    "action": "run_chapter_preflight",
                    "ok": False,
                    "blocked": True,
                    "stage": state.stage.value,
                    "next_action": "request_outline_confirmation",
                    "message": "还不能进入章节预检。请先确认大纲范围。",
                    "chapter_id": chapter_id,
                    "reason": "outline_not_confirmed",
                    "missing_items": ["outline_scope"],
                    "packet": None,
                }
        result = self.orchestrator.run_chapter_preflight(chapter_id)
        payload = self._wrap("run_chapter_preflight", result)
        payload.update(result if isinstance(result, dict) else {})
        packet = payload.pop("packet", None)
        payload["packet_ready"] = bool(isinstance(packet, dict) and packet)
        return payload

    def delegate_chapter_write(
        self,
        chapter_id: str,
        *,
        guidance: str = "",
        target_words: int = 0,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        result = self.orchestrator.delegate_writing(
            chapter_id,
            guidance=guidance,
            target_words=target_words,
            temperature=temperature,
        )
        payload = self._wrap("delegate_chapter_write", result)
        payload.update(result if isinstance(result, dict) else {})
        return payload

    def delegate_chapter_review(
        self,
        chapter_id: str,
        *,
        guidance: str = "",
        strict: bool = False,
        dimensions: list[int] | None = None,
    ) -> dict[str, Any]:
        result = self.orchestrator.review_chapter(
            chapter_id,
            guidance=guidance,
            strict=strict,
            dimensions=dimensions,
        )
        payload = self._wrap("delegate_chapter_review", result)
        payload.update(result if isinstance(result, dict) else {})
        return payload

    def _wrap(self, action: str, result: Any) -> dict[str, Any]:
        if isinstance(result, OrchestratorResult):
            return {
                "action": action,
                "ok": not result.blocked,
                "stage": result.stage.value,
                "blocked": result.blocked,
                "next_action": result.next_action,
                "message": result.message,
            }
        if isinstance(result, dict):
            payload = dict(result)
            payload.setdefault("ok", True)
            payload.setdefault("blocked", False)
            payload.setdefault("next_action", "")
            payload["action"] = action
            return payload
        return {
            "action": action,
            "ok": True,
            "blocked": False,
            "next_action": "",
            "result": result,
        }
