"""Inline character-state annotations and their rebuildable query index."""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1
DEFAULT_FIELD = "综合状态"
DEFAULT_LOOKBACK = 50
MAX_LOOKBACK = 500
MAX_SOURCE_BYTES = 2 * 1024 * 1024

NUMBER_TOKEN = r"[零〇一二三四五六七八九十百千万两\d]+"
CHAPTER_TOKEN_RE = re.compile(
    rf"(?:\bch[_-]?(?P<id>\d+)\b|第\s*(?P<title>{NUMBER_TOKEN})\s*章)",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
ANNOTATION_RE = re.compile(
    rf"^\s*//\*\*\s*"
    rf"(?P<name>[^\[\]@:：\r\n]+?)\s*"
    rf"(?:\[(?P<field>[^\]\r\n]+)\])?\s*"
    rf"(?:@(?P<chapter>(?:ch[_-]?\d+|第\s*{NUMBER_TOKEN}\s*章)))?\s*"
    rf"[：:]\s*(?P<old>.*?)\s*(?:->|→|⇒)\s*(?P<new>.*?)\s*\*\*\s*$",
    re.IGNORECASE,
)
RELATION_ANNOTATION_RE = re.compile(
    r"^\s*//\*\*\s*"
    r"(?P<source>[^~～:：\r\n]+?)\s*[~～]\s*>?\s*"
    r"(?P<target>[^:：\r\n]+?)\s*"
    r"[：:]\s*(?P<description>.+?)\s*\*\*\s*$"
)


@dataclass(frozen=True)
class CharacterStateRecord:
    name: str
    field: str
    old_state: str
    new_state: str
    chapter_id: str
    chapter_number: int
    source_kind: str
    source_path: str
    line: int

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CharacterStateRecord:
        return cls(
            name=str(value.get("name") or ""),
            field=str(value.get("field") or DEFAULT_FIELD),
            old_state=str(value.get("old_state") or ""),
            new_state=str(value.get("new_state") or ""),
            chapter_id=str(value.get("chapter_id") or ""),
            chapter_number=int(value.get("chapter_number") or 0),
            source_kind=str(value.get("source_kind") or "reference"),
            source_path=str(value.get("source_path") or ""),
            line=int(value.get("line") or 0),
        )


@dataclass(frozen=True)
class RelationAnnotationRecord:
    source: str
    target: str
    description: str
    source_path: str
    line: int


def parse_relation_annotations(
    text: str,
    *,
    source_path: str,
) -> tuple[list[RelationAnnotationRecord], list[dict[str, Any]]]:
    """Parse directed ``//**A~>B:关系**`` registrations outside code fences."""
    records: list[RelationAnnotationRecord] = []
    diagnostics: list[dict[str, Any]] = []
    fence_marker = ""
    for line_number, line in enumerate(str(text or "").splitlines(), start=1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if not fence_marker:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = ""
            continue
        if fence_marker or "//**" not in line:
            continue
        match = RELATION_ANNOTATION_RE.match(line)
        if not match:
            if "~" in line or "～" in line:
                diagnostics.append(
                    {
                        "code": "invalid_relation_annotation",
                        "path": source_path,
                        "line": line_number,
                        "message": "关系批注格式无效，应为 //**A~>B:具体关系**",
                    }
                )
            continue
        source = match.group("source").strip()
        target = match.group("target").strip()
        description = match.group("description").strip()
        if not source or not target or not description:
            diagnostics.append(
                {
                    "code": "incomplete_relation_annotation",
                    "path": source_path,
                    "line": line_number,
                    "message": "关系源、目标和具体关系均不能为空",
                }
            )
            continue
        records.append(
            RelationAnnotationRecord(
                source=source,
                target=target,
                description=description,
                source_path=source_path,
                line=line_number,
            )
        )
    return records, diagnostics


def parse_character_state_annotations(
    text: str,
    *,
    source_path: str,
    source_kind: str,
    default_chapter_id: str = "",
) -> tuple[list[CharacterStateRecord], list[dict[str, Any]]]:
    """Parse annotations while deriving chapter scope from headings when needed."""
    records: list[CharacterStateRecord] = []
    diagnostics: list[dict[str, Any]] = []
    current_chapter = canonical_chapter_id(default_chapter_id)
    fence_marker = ""

    for line_number, line in enumerate(str(text or "").splitlines(), start=1):
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if not fence_marker:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = ""
            continue
        if fence_marker:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            scoped = canonical_chapter_id(heading.group(1))
            if scoped:
                current_chapter = scoped

        if "//**" not in line:
            continue
        if RELATION_ANNOTATION_RE.match(line) or "~" in line or "～" in line:
            continue
        match = ANNOTATION_RE.match(line)
        if not match:
            diagnostics.append(
                {
                    "code": "invalid_annotation",
                    "path": source_path,
                    "line": line_number,
                    "message": "状态批注格式无效，应为 //**人物[维度]：旧状态 -> 新状态**",
                }
            )
            continue

        name = match.group("name").strip()
        field = (match.group("field") or DEFAULT_FIELD).strip()
        old_state = match.group("old").strip()
        new_state = match.group("new").strip()
        chapter_id = canonical_chapter_id(match.group("chapter") or current_chapter)
        if not name or not field or not old_state or not new_state:
            diagnostics.append(
                {
                    "code": "incomplete_annotation",
                    "path": source_path,
                    "line": line_number,
                    "message": "人物、维度、旧状态和新状态均不能为空",
                }
            )
            continue
        if not chapter_id:
            diagnostics.append(
                {
                    "code": "unscoped_annotation",
                    "path": source_path,
                    "line": line_number,
                    "message": "无法推断章节；请放在章节正文/章纲内，或添加 @ch_070",
                }
            )
            continue
        records.append(
            CharacterStateRecord(
                name=name,
                field=field,
                old_state=old_state,
                new_state=new_state,
                chapter_id=chapter_id,
                chapter_number=chapter_number(chapter_id),
                source_kind=source_kind,
                source_path=source_path,
                line=line_number,
            )
        )
    return records, diagnostics


def strip_character_state_annotations(text: str) -> str:
    """Remove valid inline state and relation metadata from reader-facing prose."""
    return "".join(
        line
        for line in str(text or "").splitlines(keepends=True)
        if not _is_inline_metadata(line.rstrip("\r\n"))
    )


def mask_character_state_annotations(text: str) -> str:
    """Hide valid annotations while preserving source line coordinates."""
    masked: list[str] = []
    for line in str(text or "").splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not _is_inline_metadata(content):
            masked.append(line)
            continue
        ending = line[len(content) :]
        masked.append(ending or "\n")
    return "".join(masked)


def _is_inline_metadata(line: str) -> bool:
    return bool(ANNOTATION_RE.match(line) or RELATION_ANNOTATION_RE.match(line))


class CharacterStateIndex:
    """Rebuildable index over outline, source documents, and manuscript files."""

    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.index_path = self.novel_root / ".openwrite" / "character-state-index.json"

    def refresh(self) -> dict[str, Any]:
        paths = self._source_paths()
        manifest = [self._document_signature(path) for path in paths]
        cached = self._load_cache()
        if cached and cached.get("documents") == manifest:
            return cached

        records: list[CharacterStateRecord] = []
        diagnostics: list[dict[str, Any]] = []
        for path in paths:
            relative = path.relative_to(self.novel_root).as_posix()
            signature = next(item for item in manifest if item["path"] == relative)
            if int(signature["size"]) > MAX_SOURCE_BYTES:
                diagnostics.append(
                    {
                        "code": "source_too_large",
                        "path": relative,
                        "line": 0,
                        "message": "文件超过 2 MB，未扫描状态批注",
                    }
                )
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                diagnostics.append(
                    {
                        "code": "source_unreadable",
                        "path": relative,
                        "line": 0,
                        "message": f"无法读取文件: {exc}",
                    }
                )
                continue
            source_kind = self._source_kind(relative)
            default_chapter = path.stem if source_kind == "actual" else ""
            parsed, issues = parse_character_state_annotations(
                text,
                source_path=relative,
                source_kind=source_kind,
                default_chapter_id=default_chapter,
            )
            records.extend(parsed)
            diagnostics.extend(issues)

        records.sort(key=_record_sort_key)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "documents": manifest,
            "records": [asdict(record) for record in records],
            "diagnostics": diagnostics,
        }
        self._save_cache(payload)
        return payload

    def query(
        self,
        name: str,
        *,
        field: str = "",
        lookback: int = DEFAULT_LOOKBACK,
        target_chapter: str = "",
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            return {"ok": False, "error": "人物名不能为空"}
        clean_field = str(field or "").strip()
        bounded_lookback = _bounded_lookback(lookback)
        payload = self.refresh()
        all_records = [
            CharacterStateRecord.from_dict(item)
            for item in payload.get("records", [])
            if isinstance(item, dict)
        ]
        target_id, target_source = (
            (canonical_chapter_id(target_chapter), "request_context")
            if canonical_chapter_id(target_chapter)
            else self.resolve_current_chapter()
        )
        target_number = chapter_number(target_id)
        name_key = _key(clean_name)
        matching_name = [record for record in all_records if _key(record.name) == name_key]
        suggestions = self._name_suggestions(clean_name, all_records)
        if not matching_name:
            return {
                "ok": True,
                "found": False,
                "name": clean_name,
                "target_chapter": target_id,
                "target_source": target_source,
                "current": [],
                "history": [],
                "suggestions": suggestions,
                "message": f"未找到 {clean_name} 的状态批注",
            }

        eligible = [
            record
            for record in matching_name
            if record.chapter_number <= target_number
            and (not clean_field or _key(record.field) == _key(clean_field))
        ]
        eligible.sort(key=_record_sort_key)
        effective = _effective_state_records(eligible)
        current_by_field: dict[str, CharacterStateRecord] = {}
        conflicts: list[dict[str, Any]] = []
        for record in effective:
            field_key = _key(record.field)
            previous = current_by_field.get(field_key)
            if previous and not _states_match(previous.new_state, record.old_state):
                conflicts.append(
                    {
                        "field": record.field,
                        "expected_old_state": previous.new_state,
                        "declared_old_state": record.old_state,
                        "chapter_id": record.chapter_id,
                        "source_path": record.source_path,
                        "line": record.line,
                    }
                )
            current_by_field[field_key] = record

        window_start = max(1, target_number - bounded_lookback + 1)
        history = [record for record in eligible if record.chapter_number >= window_start]
        current = [
            {
                "field": record.field,
                "state": record.new_state,
                "chapter_id": record.chapter_id,
                "chapter_number": record.chapter_number,
                "source_kind": record.source_kind,
                "source_path": record.source_path,
                "line": record.line,
                "within_lookback": record.chapter_number >= window_start,
            }
            for record in sorted(current_by_field.values(), key=lambda item: (_key(item.field),))
        ]
        relevant_paths = {record.source_path for record in matching_name}
        diagnostics = [
            issue
            for issue in payload.get("diagnostics", [])
            if isinstance(issue, dict) and str(issue.get("path") or "") in relevant_paths
        ][:20]
        return {
            "ok": True,
            "found": bool(current),
            "name": matching_name[0].name,
            "field": clean_field,
            "target_chapter": target_id,
            "target_source": target_source,
            "lookback": bounded_lookback,
            "window": {
                "start_chapter": f"ch_{window_start:03d}",
                "end_chapter": target_id,
            },
            "current": current,
            "history": [_history_item(record) for record in history],
            "history_count": len(history),
            "total_updates_through_target": len(eligible),
            "continuity_conflicts": conflicts,
            "diagnostics": diagnostics,
            "suggestions": suggestions,
        }

    def query_many(
        self,
        names: Iterable[str],
        *,
        target_chapter: str,
    ) -> list[dict[str, Any]]:
        return [
            result
            for name in dict.fromkeys(str(item or "").strip() for item in names)
            if name
            and (result := self.query(name, target_chapter=target_chapter)).get("found")
        ]

    def resolve_current_chapter(self) -> tuple[str, str]:
        latest_manuscript = self._latest_manuscript_chapter()
        latest_number = chapter_number(latest_manuscript)

        state_path = self.novel_root / "data" / "workflows" / "book_state.yaml"
        if state_path.is_file():
            state = _load_yaml_mapping(state_path)
            state_chapter = canonical_chapter_id(str(state.get("current_chapter") or ""))
            stage = str(state.get("stage") or "")
            active_stages = {
                "chapter_preflight",
                "drafting",
                "review_and_revise",
                "settlement",
            }
            if state_chapter and (
                stage in active_stages or chapter_number(state_chapter) >= latest_number
            ):
                return state_chapter, "book_state"

        config = _load_yaml_mapping(self.project_root / "novel_config.yaml")
        configured = canonical_chapter_id(str(config.get("current_chapter") or ""))
        if configured and chapter_number(configured) > latest_number:
            return configured, "project_config"
        if latest_manuscript:
            return latest_manuscript, "latest_manuscript"
        if configured:
            return configured, "project_config"
        return "ch_001", "default"

    def _source_paths(self) -> list[Path]:
        manuscript_paths = list((self.novel_root / "data" / "manuscript").rglob("*.md"))
        accepted: list[Path] = []
        try:
            from tools.manuscript_acceptance import ManuscriptAcceptanceService

            acceptance = ManuscriptAcceptanceService(
                self.project_root, self.novel_id
            )
            for path in manuscript_paths:
                fact = acceptance._read_json(acceptance.fact_path(path.stem))  # noqa: SLF001
                if not isinstance(fact, dict):
                    continue
                content = path.read_text(encoding="utf-8")
                if fact.get("source_revision") == acceptance.fingerprint(content):
                    accepted.append(path)
        except Exception:
            accepted = []
        candidates = [*(self.novel_root / "src").rglob("*.md"), *accepted]
        return sorted({path.resolve() for path in candidates if path.is_file()})

    def _latest_manuscript_chapter(self) -> str:
        chapter_ids = [
            canonical_chapter_id(path.stem)
            for path in (self.novel_root / "data" / "manuscript").rglob("ch_*.md")
            if path.is_file()
        ]
        chapter_ids = [item for item in chapter_ids if item]
        return max(chapter_ids, key=chapter_number) if chapter_ids else ""

    def _load_cache(self) -> dict[str, Any]:
        if not self.index_path.is_file():
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            return {}
        return payload

    def _save_cache(self, payload: dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.index_path.parent,
            prefix=f".{self.index_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(self.index_path)

    def _document_signature(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": path.relative_to(self.novel_root).as_posix(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    @staticmethod
    def _source_kind(relative: str) -> str:
        if relative == "src/outline.md":
            return "planned"
        if relative.startswith("data/manuscript/"):
            return "actual"
        return "reference"

    @staticmethod
    def _name_suggestions(
        name: str, records: list[CharacterStateRecord]
    ) -> list[str]:
        names = list(dict.fromkeys(record.name for record in records))
        contained = [candidate for candidate in names if _key(name) in _key(candidate)]
        combined = contained + difflib.get_close_matches(name, names, n=5, cutoff=0.5)
        return list(dict.fromkeys(combined))[:5]


def canonical_chapter_id(value: str) -> str:
    match = CHAPTER_TOKEN_RE.search(str(value or ""))
    if not match:
        return ""
    token = match.group("id") or match.group("title") or ""
    number = _chapter_token_number(token)
    return f"ch_{number:03d}" if number > 0 else ""


def chapter_number(value: str) -> int:
    canonical = canonical_chapter_id(value)
    return int(canonical.rsplit("_", 1)[-1]) if canonical else 0


def _chapter_token_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    small_units = {"十": 10, "百": 100, "千": 1000}
    total = section = digit = 0
    for character in value:
        if character in digits:
            digit = digits[character]
        elif character in small_units:
            section += (digit or 1) * small_units[character]
            digit = 0
        elif character == "万":
            total += (section + digit) * 10_000
            section = digit = 0
    return total + section + digit


def _source_priority(source_kind: str) -> int:
    priority = {"planned": 0, "reference": 1, "actual": 2}
    return priority.get(source_kind, 1)


def _record_sort_key(record: CharacterStateRecord) -> tuple[int, int, str, int]:
    return (
        record.chapter_number,
        _source_priority(record.source_kind),
        record.source_path,
        record.line,
    )


def _effective_state_records(
    records: Iterable[CharacterStateRecord],
) -> list[CharacterStateRecord]:
    """Select the strongest source kind for each field in each chapter."""
    selected: dict[tuple[str, str, str], list[CharacterStateRecord]] = {}
    for record in records:
        key = (_key(record.name), _key(record.field), record.chapter_id)
        current = selected.get(key)
        if not current or _source_priority(record.source_kind) > _source_priority(
            current[0].source_kind
        ):
            selected[key] = [record]
        elif _source_priority(record.source_kind) == _source_priority(
            current[0].source_kind
        ):
            current.append(record)
    return sorted(
        (record for group in selected.values() for record in group),
        key=_record_sort_key,
    )


def _history_item(record: CharacterStateRecord) -> dict[str, Any]:
    return {
        "field": record.field,
        "old_state": record.old_state,
        "new_state": record.new_state,
        "chapter_id": record.chapter_id,
        "chapter_number": record.chapter_number,
        "source_kind": record.source_kind,
        "source_path": record.source_path,
        "line": record.line,
    }


def _bounded_lookback(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_LOOKBACK
    return max(1, min(MAX_LOOKBACK, parsed))


def _states_match(previous: str, declared: str) -> bool:
    placeholders = {"", "?", "-", "未知", "未记录", "不明"}
    return declared.strip() in placeholders or previous.strip() == declared.strip()


def _key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}
