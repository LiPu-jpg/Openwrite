import yaml
import re
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

from tools.frontmatter import parse_toml_front_matter


def sync_all_profiles_to_cards(src_dir: Path, data_dir: Path) -> None:
    src_chars = src_dir / "characters"
    if not src_chars.exists():
        return

    cards_dir = data_dir / "characters" / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)

    for md_file in src_chars.glob("*.md"):
        card_data = parse_profile_to_card(md_file)
        if card_data:
            card_path = cards_dir / f"{md_file.stem}.yaml"
            # Atomic write: a bare open(...,"w") truncates in place, and the
            # freshness check is mtime-based, so a crash mid-write leaves a card
            # that reads as current but is only half there.
            descriptor, temporary_name = tempfile.mkstemp(
                prefix="." + md_file.stem + ".", suffix=".tmp", dir=str(cards_dir)
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    yaml.dump(
                        card_data, handle, allow_unicode=True, default_flow_style=False, sort_keys=False
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, card_path)
            finally:
                temporary.unlink(missing_ok=True)


def parse_profile_to_card(md_file: Path) -> Optional[Dict[str, Any]]:
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    meta, body = parse_toml_front_matter(content)
    lines = body.split("\n")

    name = str(meta.get("name", "")).strip()
    identity = str(meta.get("occupation") or meta.get("identity") or "").strip()
    age = meta.get("age")
    appearance = {}
    summary = str(meta.get("summary", "")).strip()
    background = ""
    personality: List[str] = []
    tier = str(meta.get("tier", "普通配角")).strip() or "普通配角"
    relationships = meta.get("related", [])

    current_section = None
    appearance_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            if level == 1:
                name = title
            elif level == 2:
                lowered = title.lower()
                if title in ("外貌", "外貌特征") or lowered == "appearance":
                    current_section = "appearance"
                    appearance_lines = []
                elif title in ("背景",) or lowered == "background":
                    current_section = "background"
                elif title in ("性格",) or lowered == "personality":
                    current_section = "personality"
                else:
                    current_section = None
            i += 1
            continue

        if current_section == "appearance":
            item_match = re.match(r"^-\s*(.+)$", stripped)
            if item_match:
                item_text = item_match.group(1).strip()
                if (
                    "中等" in item_text
                    or "偏瘦" in item_text
                    or "偏胖" in item_text
                    or "健壮" in item_text
                ):
                    appearance["build"] = item_text
                elif (
                    "黑眼圈" in item_text
                    or "眼镜" in item_text
                    or "疤痕" in item_text
                    or "特征" in item_text
                ):
                    appearance["features"] = item_text
                elif (
                    "格子衫" in item_text
                    or "西装" in item_text
                    or "T恤" in item_text
                    or "服装" in item_text
                ):
                    appearance["clothing"] = item_text
                else:
                    if "features" not in appearance:
                        appearance["features"] = item_text
                    else:
                        appearance["clothing"] = item_text
            elif stripped.startswith("#"):
                current_section = None
                i -= 1
            else:
                if appearance_lines:
                    appearance_lines[-1] += " " + stripped
                else:
                    appearance_lines.append(stripped)
            i += 1
            continue

        if current_section == "background":
            background = f"{background} {stripped}".strip()
            i += 1
            continue

        if current_section == "personality":
            item_match = re.match(r"^-\s*(.+)$", stripped)
            if item_match:
                personality.append(item_match.group(1).strip())
            elif stripped.startswith("#"):
                current_section = None
                i -= 1
            i += 1
            continue

        kv_match = re.match(r"^-\s*([^:]+):\s*(.+)$", stripped)
        if kv_match:
            key = kv_match.group(1).strip()
            value = kv_match.group(2).strip()

            if key in ("职业", "身份", "角色"):
                identity = value
            elif key in ("年龄", "岁数"):
                age_match = re.search(r"\d+", value)
                if age_match:
                    age = int(age_match.group())

        i += 1

    for line_text in appearance_lines:
        parts = [p.strip() for p in line_text.split("，") if p.strip()]
        for part in parts:
            if any(k in part for k in ["中等", "偏瘦", "偏胖", "健壮", "肥胖", "苗条"]):
                appearance["build"] = part
            elif any(k in part for k in ["黑眼圈", "眼镜", "疤痕", "特征", "痘痘", "纹身"]):
                appearance["features"] = part
            elif any(k in part for k in ["格子衫", "西装", "T恤", "服装", "裙子", "裤子", "外套"]):
                appearance["clothing"] = part
            else:
                if "features" not in appearance:
                    appearance["features"] = part
                elif "clothing" not in appearance:
                    appearance["clothing"] = part

    if not name:
        name = _extract_md_heading(body)
    if not name and body.strip():
        name = md_file.stem
    if not background:
        background = _extract_md_section(body, "背景") or _extract_md_section(body, "background")
    if not personality:
        personality = _extract_md_list(body, "性格") or _extract_md_list(body, "personality")
    if not name:
        return None

    card: Dict[str, Any] = {
        "id": str(meta.get("id", md_file.stem)).strip() or md_file.stem,
        "name": name,
        "tier": tier,
        "age": age,
        "occupation": identity,
        "identity": identity,
        "brief": summary,
        "background": background,
        "personality": personality,
        "relationships": relationships if isinstance(relationships, list) else [],
    }

    if appearance:
        card["appearance"] = appearance

    return card


def _extract_md_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_md_section(text: str, section_name: str) -> str:
    pattern = rf"^##\s+[^\n]*{re.escape(section_name)}[^\n]*\n(.*?)(?=\n##|\Z)"
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_md_list(text: str, section_name: str) -> List[str]:
    section = _extract_md_section(text, section_name)
    if not section:
        return []
    return [item.strip() for item in re.findall(r"^[-*]\s+(.+)$", section, re.MULTILINE)]
