"""Local serial-writing assets and deterministic manuscript diagnostics."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import yaml

from tools.character_state_index import strip_character_state_annotations
from tools.file_ops import atomic_write
from tools.novel_workspace import count_writing_units


def manuscript_metrics(content: str, concrete_nouns: list[str] | None = None) -> dict[str, Any]:
    body = strip_character_state_annotations(content)
    body = re.sub(r"(?m)^#{1,6}\s+.*$", "", body).strip()
    paragraphs = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    sentences = [s for s in re.split(r"[。！？.!?]+|\n", body) if count_writing_units(s)]

    def distribution(items: list[str]) -> dict[str, Any]:
        lengths = sorted(count_writing_units(item) for item in items)
        return {
            "count": len(lengths),
            "p50": lengths[max(0, math.ceil(len(lengths) * 0.5) - 1)] if lengths else 0,
            "p90": lengths[max(0, math.ceil(len(lengths) * 0.9) - 1)] if lengths else 0,
            "mean": round(sum(lengths) / len(lengths), 2) if lengths else 0,
        }

    units = count_writing_units(body)
    # Quote spans are non-overlapping and only count as dialogue when closed.
    quotes = re.findall(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', body)
    nouns = list(dict.fromkeys(concrete_nouns or []))
    noun_pattern = "|".join(re.escape(term) for term in sorted(nouns, key=len, reverse=True))
    noun_count = len(list(re.finditer(noun_pattern, body))) if noun_pattern else 0
    return {
        "writing_units": units,
        "hanzi_count": len(re.findall(r"[\u3400-\u9fff]", body)),
        "paragraph_count": len(paragraphs),
        "sentences": distribution(sentences),
        "paragraphs": distribution(paragraphs),
        "dialogue_ratio": round(sum(count_writing_units(q) for q in quotes) / units, 4)
        if units
        else 0,
        "concrete_nouns": {
            "method": "project_lexicon" if nouns else "not_configured",
            "count": noun_count if nouns else None,
            "per_1000_units": round(noun_count / units * 1000, 2) if nouns and units else None,
        },
        "source_revision": revision(content),
    }


def revision(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def term_findings(content: str, terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for term in terms:
        word = term["term"]
        occurrences = list(re.finditer(re.escape(word), content))
        if term.get("forbidden"):
            for match in occurrences:
                findings.append(
                    {
                        "kind": "forbidden_term",
                        "term": word,
                        "start": match.start(),
                        "end": match.end(),
                        "line": content.count("\n", 0, match.start()) + 1,
                        "evidence": match.group(),
                        "suggestion": term.get("replacement", ""),
                    }
                )
        elif len(occurrences) < term.get("min_occurrences", 0):
            findings.append(
                {
                    "kind": "missing_term",
                    "term": word,
                    "actual": len(occurrences),
                    "minimum": term["min_occurrences"],
                    "start": None,
                    "end": None,
                }
            )
    return findings


def overlap_report(
    content: str, references: dict[str, str], *, window: int = 12, threshold: float = 0.05
) -> dict[str, Any]:
    """Union of matched 12-character windows, with original codepoint offsets."""
    positions = [i for i, c in enumerate(content) if c.isalnum()]
    normalized = "".join(content[i] for i in positions)
    reports = []
    for name, source in references.items():
        text = "".join(c for c in source if c.isalnum())
        windows = {text[i : i + window] for i in range(max(0, len(text) - window + 1))}
        ranges: list[list[int]] = []
        for i in range(max(0, len(normalized) - window + 1)):
            if normalized[i : i + window] in windows:
                if ranges and i <= ranges[-1][1]:
                    ranges[-1][1] = i + window
                else:
                    ranges.append([i, i + window])
        matched = sum(end - start for start, end in ranges)
        ratio = matched / len(normalized) if normalized else 0
        reports.append(
            {
                "source": name,
                "matched_characters": matched,
                "ratio": round(ratio, 4),
                "flagged": ratio > threshold,
                "match_count": len(ranges),
                "spans": [
                    {
                        "start": positions[start],
                        "end": positions[end - 1] + 1,
                        "text": content[positions[start] : positions[end - 1] + 1],
                    }
                    for start, end in ranges[:100]
                ],
            }
        )
    seen: dict[str, int] = {}
    duplicates = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", content):
        key = "".join(c for c in match.group() if c.isalnum())
        if len(key) < window:
            continue
        if key in seen:
            duplicates.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "first_start": seen[key],
                    "text": match.group(),
                }
            )
        else:
            seen[key] = match.start()
    return {
        "window": window,
        "threshold": threshold,
        "offset_unit": "unicode_codepoints",
        "references": reports,
        "duplicate_paragraphs": duplicates,
        "source_revision": revision(content),
    }


def join_segment(previous: str, continuation: str, *, similarity_threshold: float = 0.96) -> str:
    """Remove repeated prose while preserving short dialogue and changed numbers."""
    from difflib import SequenceMatcher

    if not 0.9 <= similarity_threshold <= 1.0:
        raise ValueError("segment_similarity_threshold must be between 0.9 and 1.0")
    new = re.sub(r"\A\s*#{1,6}\s+[^\n]*\n", "", continuation).strip()
    old = previous.rstrip()
    for length in range(min(len(old), len(new), 3000), 11, -1):
        if old.endswith(new[:length]):
            new = new[length:].lstrip()
            break
    existing = {p.strip() for p in re.split(r"\n\s*\n", old) if len(p.strip()) >= 12}
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", new):
        key = paragraph.strip()
        repeated = key in existing
        if not repeated and len(key) >= 40:
            repeated = any(
                len(other) >= 40
                and re.findall(r"\d+", key) == re.findall(r"\d+", other)
                and SequenceMatcher(None, key, other, autojunk=False).ratio()
                >= similarity_threshold
                for other in existing
            )
        if key and (len(key) < 12 or not repeated):
            paragraphs.append(paragraph)
            if len(key) >= 12:
                existing.add(key)
    return old + ("\n\n" + "\n\n".join(paragraphs) if paragraphs else "")


class WritingAssets:
    def __init__(self, project_root: Path, novel_id: str):
        self.root = Path(project_root).resolve() / "data" / "novels" / novel_id
        self.path = self.root / "src" / "writing" / "assets.yaml"

    def load(self) -> dict[str, Any]:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}
        return self.validate(raw or {})

    @staticmethod
    def validate(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("Writing assets must be an object")
        terms = raw.get("terms", [])
        if not isinstance(terms, list) or len(terms) > 1000:
            raise ValueError("terms must be a list of at most 1000 entries")
        if type(raw.get("review_terms", True)) is not bool:
            raise ValueError("review_terms must be boolean")
        names = set()
        for item in terms:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("term"), str)
                or not item["term"].strip()
            ):
                raise ValueError("Each term requires a nonempty term")
            if item["term"] in names or len(item["term"]) > 200:
                raise ValueError("Terms must be unique and at most 200 characters")
            names.add(item["term"])
            minimum = item.get("min_occurrences", 0)
            if type(minimum) is not int or not 0 <= minimum <= 1000:
                raise ValueError("min_occurrences must be 0-1000")
            if type(item.get("forbidden", False)) is not bool:
                raise ValueError("forbidden must be boolean")
            if item.get("forbidden") and minimum:
                raise ValueError("A forbidden term cannot require occurrences")
            for key in ("example", "replacement"):
                if not isinstance(item.get(key, ""), str) or len(item.get(key, "")) > 2000:
                    raise ValueError(f"{key} must be text of at most 2000 characters")
        characters = raw.get("character_groups", {})
        if not isinstance(characters, dict):
            raise ValueError("character_groups must be an object keyed by character name")
        for groups in characters.values():
            if not isinstance(groups, list) or len(groups) > 100:
                raise ValueError("Character groups must be a list of at most 100 entries")
            ids = set()
            for group in groups:
                if not isinstance(group, dict) or not all(
                    isinstance(group.get(k), str) and group[k].strip() for k in ("id", "text")
                ):
                    raise ValueError("Each group needs id and text")
                if group["id"] in ids or len(group["text"]) > 2000:
                    raise ValueError("Group IDs must be unique and text at most 2000 characters")
                ids.add(group["id"])
        threshold = raw.get("overlap_threshold", 0.05)
        if type(threshold) not in (float, int) or not 0 <= threshold <= 1:
            raise ValueError("overlap_threshold must be 0-1")
        nouns = raw.get("concrete_nouns", [])
        if (
            not isinstance(nouns, list)
            or len(nouns) > 10000
            or not all(isinstance(n, str) and n for n in nouns)
        ):
            raise ValueError("concrete_nouns must be a list of nonempty strings")
        return {
            **raw,
            "terms": terms,
            "character_groups": characters,
            "concrete_nouns": nouns,
            "overlap_threshold": threshold,
            "review_terms": raw.get("review_terms", True) is not False,
        }

    def save(self, raw: dict[str, Any], expected_revision: str) -> dict[str, Any]:
        current = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        if expected_revision != (revision(current) if current else ""):
            raise ValueError("Writing assets revision changed; refresh before saving")
        data = self.validate(raw)
        atomic_write(self.path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        return self.surface()

    def surface(self) -> dict[str, Any]:
        text = self.path.read_text(encoding="utf-8") if self.path.is_file() else ""
        return {
            "assets": self.load(),
            "revision": revision(text) if text else "",
            "anchors": [
                {"path": name, "characters": len(value), "revision": revision(value)}
                for name, value in self.anchors().items()
            ],
        }

    def save_anchor(self, name: str, content: str, expected_revision: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_\-\u3400-\u9fff]{1,80}\.md", name):
            raise ValueError("Anchor name must be a simple .md filename")
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            raise ValueError("Anchor must contain 1-20000 characters")
        path = self.root / "anchor" / name
        if path.is_symlink():
            raise ValueError("Anchor cannot be a symlink")
        old = path.read_text(encoding="utf-8") if path.is_file() else ""
        if expected_revision != (revision(old) if old else ""):
            raise ValueError("Anchor revision changed")
        atomic_write(path, content)
        return self.surface()

    def mark_usage(self, chapter_id: str, groups: dict[str, list[str]]) -> dict[str, Any]:
        if not re.fullmatch(r"ch_\d+", chapter_id) or not isinstance(groups, dict):
            raise ValueError("Chapter and character groups are required")
        configured = self.load()["character_groups"]
        for name, ids in groups.items():
            known = {g["id"] for g in configured.get(name, [])}
            if not isinstance(ids, list) or not all(isinstance(v, str) and v in known for v in ids):
                raise ValueError("Unknown character group")
        atomic_write(
            self.root / "data" / "writing_usage" / f"{chapter_id}.yaml",
            yaml.safe_dump({"chapter_id": chapter_id, "used": groups}, allow_unicode=True),
        )
        return {"chapter_id": chapter_id, "used": groups}

    def anchors(self) -> dict[str, str]:
        result = {}
        # Bounded deterministic sampling; every reference remains available to overlap checks.
        for path in sorted((self.root / "anchor").glob("*.md"))[:100]:
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= 1_000_000:
                result[path.relative_to(self.root).as_posix()] = path.read_text(encoding="utf-8")
        return result

    def context(self, chapter_id: str) -> dict[str, Any]:
        data = self.load()
        chapter = int(chapter_id.removeprefix("ch_"))
        anchors = self.anchors()
        names = list(anchors)
        sample = {}
        if names:
            name = names[(chapter - 1) % len(names)]
            sample[name] = anchors[name][:1200]
        selected = {}
        for name, groups in data["character_groups"].items():
            count = min(3, len(groups))
            selected[name] = [
                groups[((chapter - 1) * count + i) % len(groups)] for i in range(count)
            ]
        return {
            "term_table": data["terms"],
            "review_terms": data["review_terms"],
            "anchor_samples": sample,
            "character_group_selection": selected,
        }

    def inspect_chapter(self, chapter_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"ch_\d+", chapter_id):
            raise ValueError("Invalid chapter ID")
        paths = sorted((self.root / "data" / "manuscript").glob(f"**/{chapter_id}.md"))
        if len(paths) != 1:
            raise ValueError("Chapter missing or ambiguous")
        content = paths[0].read_text(encoding="utf-8")
        data = self.load()
        references = self.anchors()
        earlier = [
            p
            for p in (self.root / "data" / "manuscript").glob("**/ch_*.md")
            if re.fullmatch(r"ch_\d+", p.stem) and int(p.stem[3:]) < int(chapter_id[3:])
        ]
        for path in sorted(earlier, key=lambda p: int(p.stem[3:]))[-3:]:
            references[path.relative_to(self.root).as_posix()] = path.read_text(encoding="utf-8")
        return {
            "chapter_id": chapter_id,
            "metrics": manuscript_metrics(content, data["concrete_nouns"]),
            "terms": term_findings(content, data["terms"]),
            "overlap": overlap_report(content, references, threshold=data["overlap_threshold"]),
            "character_groups": self.context(chapter_id)["character_group_selection"],
            "character_group_usage": yaml.safe_load(
                (self.root / "data" / "writing_usage" / f"{chapter_id}.yaml").read_text()
            )
            if (self.root / "data" / "writing_usage" / f"{chapter_id}.yaml").is_file()
            else {"used": {}},
        }
