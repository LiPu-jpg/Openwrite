"""Countable chapter-group audits and an author-controlled drift ledger."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from tools.file_ops import atomic_write
from tools.outline_parser import OutlineMdParser
from tools.outline_tree import build_outline_structure, mutate_outline_structure
from tools.project_lock import ProjectWriteLock
from tools.writing_assets import manuscript_metrics, revision
from tools.writing_targets import normalize_writing_targets

FUNCTIONS = {"推进", "揭示", "关系", "代价"}
DRIFT_KINDS = {"growth", "escape", "dilution", "snowball"}
IMPACTS = {"local", "section", "arc"}


class ArcAuditService:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.root = self.project_root / "data" / "novels" / novel_id
        self.outline = self.root / "src" / "outline.md"
        self.store = self.root / "data" / "arc_audit"
        self.ledger_path = self.store / "ledger.json"
        self.transaction_path = self.store / "transaction.json"

    def _hierarchy(self):
        text = self.outline.read_text(encoding="utf-8") if self.outline.is_file() else ""
        return OutlineMdParser().parse(text, self.novel_id)

    def _chapters(self, group_id: str = "") -> list:
        hierarchy = self._hierarchy()
        if not group_id:
            return hierarchy.chapters
        node = hierarchy.get_node(group_id)
        if node is None:
            raise ValueError("Unknown chapter group")
        if group_id.startswith("arc_"):
            return hierarchy.get_chapters_by_arc(group_id)
        if group_id.startswith("sec_"):
            return [ch for ch in hierarchy.chapters if ch.parent_id == group_id]
        raise ValueError("group_id must name an arc or section")

    def ledger(self) -> dict[str, Any]:
        if self.transaction_path.is_file():
            raise ValueError(
                "Drift reconciliation was interrupted; "
                "recover_transaction with confirm=true before continuing"
            )
        return (
            json.loads(self.ledger_path.read_text(encoding="utf-8"))
            if self.ledger_path.is_file()
            else {"revision": 0, "entries": [], "groups": {}}
        )

    def _commit(self, ledger: dict[str, Any], outline: str | None) -> None:
        if outline is not None:
            previous = self.outline.read_bytes().decode("utf-8")
            atomic_write(
                self.transaction_path,
                json.dumps(
                    {
                        "before_outline": revision(previous),
                        "after_outline": revision(outline),
                        "outline": outline,
                        "ledger": ledger,
                        "before_revision": ledger["revision"] - 1,
                    },
                    ensure_ascii=False,
                ),
            )
            atomic_write(self.outline, outline)
        atomic_write(self.ledger_path, json.dumps(ledger, ensure_ascii=False, indent=2))
        if outline is not None:
            self.transaction_path.unlink()

    def _recover_transaction(self) -> dict[str, Any]:
        if not self.transaction_path.is_file():
            return self.audit()
        transaction = json.loads(self.transaction_path.read_text(encoding="utf-8"))
        current = revision(self.outline.read_bytes().decode("utf-8"))
        stored = (
            json.loads(self.ledger_path.read_text())
            if self.ledger_path.is_file()
            else {"revision": 0}
        )
        if current not in {transaction["before_outline"], transaction["after_outline"]} or stored[
            "revision"
        ] not in {transaction["before_revision"], transaction["ledger"]["revision"]}:
            raise ValueError(
                "Outline or ledger changed after interruption; "
                "preserve the transaction and baseline for manual reconciliation"
            )
        atomic_write(self.outline, transaction["outline"])
        atomic_write(
            self.ledger_path, json.dumps(transaction["ledger"], ensure_ascii=False, indent=2)
        )
        self.transaction_path.unlink()
        return self.audit()

    def audit(self, group_id: str = "", start: str = "", end: str = "") -> dict[str, Any]:
        chapters = self._chapters(group_id)
        for value in (start, end):
            if value and not re.fullmatch(r"ch_\d+", value):
                raise ValueError("Chapter bounds must be chapter IDs")
        if start and end and int(start[3:]) > int(end[3:]):
            raise ValueError("Start must not follow end")
        chapters = [
            ch
            for ch in chapters
            if (not start or int(ch.node_id[3:]) >= int(start[3:]))
            and (not end or int(ch.node_id[3:]) <= int(end[3:]))
        ]
        config_path = self.project_root / "novel_config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        default = normalize_writing_targets(config.get("writing_targets"))["chapter_words"]
        rows = []
        for ch in chapters:
            paths = list((self.root / "data" / "manuscript").glob(f"**/{ch.node_id}.md"))
            actual = (
                manuscript_metrics(paths[0].read_text(encoding="utf-8"))["writing_units"]
                if len(paths) == 1
                else None
            )
            planned = ch.word_budget or ch.estimated_words or default
            promise = re.split(r"\s*(?:->|→)\s*", ch.promise, maxsplit=1)
            has_change = (
                len(promise) == 2
                and all(p.strip() for p in promise)
                and promise[0].strip() != promise[1].strip()
            )
            rows.append(
                {
                    "chapter_id": ch.node_id,
                    "promise": ch.promise,
                    "declared_state_change": has_change,
                    "promise_verified_in_prose": None,
                    "function": ch.function,
                    "payoff_of": ch.payoff_of,
                    "word_budget": planned,
                    "actual_words": actual,
                    "deviation": round((actual - planned) / planned, 4)
                    if actual is not None
                    else None,
                    "missing_fields": [
                        key
                        for key, value in {
                            "promise": ch.promise,
                            "function": ch.function,
                            "word_budget": ch.word_budget or ch.estimated_words,
                        }.items()
                        if not value
                    ],
                    "manuscript_status": "current"
                    if len(paths) == 1
                    else "missing"
                    if not paths
                    else "ambiguous",
                }
            )
        ids = {row["chapter_id"] for row in rows}
        dag_path = self.root / "data" / "foreshadowing" / "dag.yaml"
        dag = (
            yaml.safe_load(dag_path.read_text(encoding="utf-8")) or {} if dag_path.is_file() else {}
        )
        nodes = dag.get("nodes") or {}
        if not isinstance(nodes, dict):
            raise ValueError("Foreshadowing nodes must be a mapping")
        edges = [
            {
                "from": fid,
                "to": row["chapter_id"],
                "type": "payoff_of",
                "source": "outline_declaration",
                "known": fid in nodes,
            }
            for row in rows
            for fid in row["payoff_of"]
        ]
        created = [fid for fid, node in nodes.items() if node.get("created_at") in ids]
        declared = set(edge["from"] for edge in edges)
        recovered = [fid for fid in declared if fid in nodes and nodes[fid].get("status") == "已收"]
        last_number = max((int(cid[3:]) for cid in ids), default=0)
        overdue = [
            fid
            for fid, node in nodes.items()
            if node.get("status") not in {"已收", "废弃"}
            and re.fullmatch(r"ch_\d+", str(node.get("target_chapter") or ""))
            and int(node["target_chapter"][3:]) < last_number
        ]
        ledger = self.ledger()
        drifts = [entry for entry in ledger["entries"] if entry["chapter_id"] in ids]

        def streaks(predicate):
            result, streak = [], []
            for row in rows:
                if predicate(row):
                    streak.append(row["chapter_id"])
                else:
                    if len(streak) >= 3:
                        result.append(streak)
                    streak = []
            if len(streak) >= 3:
                result.append(streak)
            return result

        function_counts = Counter(value for row in rows for value in row["function"])
        actual_total = sum(row["actual_words"] for row in rows if row["actual_words"] is not None)
        planned_total = sum(row["word_budget"] for row in rows)
        return {
            "schema_version": "openwrite.outline-audit.v1",
            "group_id": group_id,
            "outline_revision": build_outline_structure(self.root).get("revision", ""),
            "available_groups": [
                {"id": node.node_id, "title": node.title}
                for node in [*self._hierarchy().arcs, *self._hierarchy().sections]
            ],
            "chapters": rows,
            "ledger": ledger,
            "words": {
                "planned": planned_total,
                "actual": actual_total,
                "missing_chapters": [
                    row["chapter_id"] for row in rows if row["actual_words"] is None
                ],
                "deviation": round((actual_total - planned_total) / planned_total, 4)
                if planned_total
                else None,
            },
            "completeness": {
                "complete_chapters": sum(not row["missing_fields"] for row in rows),
                "total": len(rows),
            },
            "progression": {
                "declared_changes": sum(row["declared_state_change"] for row in rows),
                "no_declared_change_streaks": streaks(lambda row: not row["declared_state_change"]),
            },
            "functions": {
                "counts": {key: function_counts[key] for key in sorted(FUNCTIONS)},
                "streaks": {
                    key: streaks(lambda row, key=key: key in row["function"])
                    for key in sorted(FUNCTIONS)
                },
            },
            "foreshadowing": {
                "created": created,
                "declared_payoffs": sorted(declared),
                "confirmed_recovered": recovered,
                "net_new_debt": len(created) - len(recovered),
                "overdue": overdue,
                "payoff_edges": edges,
            },
            "drift": {
                "total": len(drifts),
                "rewrites": sum(entry["rewrite"] for entry in drifts),
                "not_written_back": sum(not entry["outline_written"] for entry in drifts),
                "kinds": dict(Counter(entry["kind"] for entry in drifts)),
            },
        }

    def _baseline(self, group_id: str) -> str:
        baseline_id = "baseline_" + uuid4().hex[:12]
        folder = self.store / "baselines" / baseline_id
        paths = [self.outline]
        for chapter in self._chapters(group_id):
            paths.extend((self.root / "data" / "manuscript").glob(f"**/{chapter.node_id}.md"))
        manifest = {}
        for path in paths:
            if path.is_file():
                relative = path.relative_to(self.root).as_posix()
                data = path.read_bytes().decode("utf-8")
                atomic_write(folder / relative, data)
                manifest[relative] = revision(data)
        atomic_write(folder / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return baseline_id

    def change(self, payload: dict[str, Any]) -> dict[str, Any]:
        with ProjectWriteLock(self.project_root, self.novel_id, operation="arc_reconcile"):
            if payload.get("action") == "recover_transaction":
                if payload.get("confirm") is not True:
                    raise ValueError("Transaction recovery requires confirm=true")
                return self._recover_transaction()
            ledger = self.ledger()
            if (
                type(payload.get("expected_revision")) is not int
                or payload["expected_revision"] != ledger["revision"]
            ):
                raise ValueError("Drift ledger revision changed; refresh before writing")
            action = payload.get("action")
            group_id = str(payload.get("group_id") or "")
            chapters = self._chapters(group_id)
            if not group_id or not chapters:
                raise ValueError("A nonempty chapter group is required")
            ids = {ch.node_id for ch in chapters}
            group = ledger["groups"].setdefault(group_id, {"frozen": False, "rewrite_budget": 2})
            now = datetime.now(timezone.utc).isoformat()
            changed_outline = None
            if action == "drift_entry":
                if not group_id.startswith("sec_"):
                    raise ValueError("Drift budget belongs to a section; supply its sec_* group_id")
                if group["frozen"]:
                    raise ValueError("Group is frozen; reconcile and replan before adding drift")
                chapter_id = str(payload.get("chapter_id") or "")
                kind, impact = payload.get("kind"), payload.get("impact")
                note = str(payload.get("note") or "").strip()
                if (
                    chapter_id not in ids
                    or kind not in DRIFT_KINDS
                    or impact not in IMPACTS
                    or not note
                ):
                    raise ValueError(
                        "Drift requires a chapter in this group, kind, impact and note"
                    )
                if type(payload.get("rewrite", True)) is not bool:
                    raise ValueError("rewrite must be boolean")
                baseline = self._baseline(group_id)
                ledger["entries"].append(
                    {
                        "id": "drift_" + uuid4().hex[:12],
                        "group_id": group_id,
                        "chapter_id": chapter_id,
                        "kind": kind,
                        "impact": impact,
                        "rewrite": payload.get("rewrite", True),
                        "note": note,
                        "outline_written": False,
                        "status": "open",
                        "baseline_id": baseline,
                        "created_at": now,
                    }
                )
                count = sum(
                    e["rewrite"] and e["status"] in {"open", "recovery_planned", "frozen"}
                    for e in ledger["entries"]
                    if e["group_id"] == group_id
                )
                if count > group["rewrite_budget"]:
                    group.update(frozen=True, reason="rewrite_budget_exceeded")
            elif action == "arc_reconcile":
                decision = payload.get("decision")
                if (
                    decision not in {"absorb", "recover", "freeze"}
                    or payload.get("confirm") is not True
                ):
                    raise ValueError("Reconcile requires absorb/recover/freeze and confirm=true")
                requested = payload.get("entry_ids")
                if (
                    not isinstance(requested, list)
                    or not requested
                    or not all(isinstance(v, str) for v in requested)
                    or len(set(requested)) != len(requested)
                ):
                    raise ValueError("entry_ids must be a nonempty unique list")
                selected = [
                    e
                    for e in ledger["entries"]
                    if e["id"] in requested and e["group_id"] == group_id
                ]
                if len(selected) != len(requested):
                    raise ValueError("Unknown drift entry in group")
                if any(
                    entry["status"] not in {"open", "recovery_planned", "frozen"}
                    for entry in selected
                ):
                    raise ValueError("Selected drift was already resolved")
                baseline = self._baseline(group_id)
                if decision == "absorb":
                    updates = payload.get("outline_updates")
                    if (
                        not isinstance(updates, list)
                        or not updates
                        or any(
                            not isinstance(u, dict) or u.get("node_id") not in ids for u in updates
                        )
                    ):
                        raise ValueError(
                            "Absorption requires outline_updates for chapters in this group"
                        )
                    updated_ids = {u["node_id"] for u in updates}
                    if any(e["chapter_id"] not in updated_ids for e in selected):
                        raise ValueError("Every absorbed chapter requires an outline update")
                    result = mutate_outline_structure(
                        self.root,
                        operation="set_meta",
                        revision=str(payload.get("outline_revision") or ""),
                        updates=updates,
                    )
                    changed_outline = result["content"]
                    for entry in selected:
                        entry.update(status="absorbed", outline_written=True)
                elif decision == "recover":
                    plan = str(payload.get("plan") or "").strip()
                    target = str(payload.get("target_chapter_id") or "")
                    if not plan or target not in {ch.node_id for ch in self._hierarchy().chapters}:
                        raise ValueError(
                            "Recovery requires an authored plan and a planned target chapter"
                        )
                    if any(int(target[3:]) <= int(e["chapter_id"][3:]) for e in selected):
                        raise ValueError("Recovery target must follow the drifting chapter")
                    for entry in selected:
                        entry.update(
                            status="recovery_planned", recovery_plan=plan, target_chapter_id=target
                        )
                else:
                    group.update(frozen=True, reason="author_decision")
                    for entry in selected:
                        entry["status"] = "frozen"
                for entry in selected:
                    entry.update(reconciled_at=now, reconciliation_baseline=baseline)
                if decision == "absorb" and payload.get("resume") is True:
                    outstanding = sum(
                        e["rewrite"] and e["status"] in {"open", "recovery_planned", "frozen"}
                        for e in ledger["entries"]
                        if e["group_id"] == group_id
                    )
                    if outstanding <= group["rewrite_budget"]:
                        group.update(frozen=False, reason="replanned")
            else:
                raise ValueError("Unknown drift action")
            ledger["revision"] += 1
            ledger["updated_at"] = now
            self._commit(ledger, changed_outline)
            return self.audit(group_id)

    def require_unfrozen(self, chapter_id: str) -> None:
        for group_id, group in self.ledger()["groups"].items():
            if group.get("frozen") and chapter_id in {
                ch.node_id for ch in self._chapters(group_id)
            }:
                raise ValueError(f"Chapter group {group_id} is frozen; reconcile and replan first")

    def chapter_guidance(self, chapter_id: str) -> list[str]:
        return [
            f"{entry['chapter_id']}: {entry['recovery_plan']}"
            for entry in self.ledger()["entries"]
            if entry.get("status") == "recovery_planned"
            and entry.get("target_chapter_id") == chapter_id
        ]
