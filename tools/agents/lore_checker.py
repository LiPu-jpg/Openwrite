"""Lore checker for timeline/world consistency checks."""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class LoreCheckResult:
    """Consistency check result."""

    errors: List[str]
    warnings: List[str]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


class LoreCheckerAgent:
    """Performs lightweight rule checks on generated draft text."""

    def check(self, draft: str, constraints: Dict[str, str]) -> LoreCheckResult:
        forbidden_raw = constraints.get("forbidden", "")
        required_raw = constraints.get("required", "")

        forbidden = [item.strip() for item in forbidden_raw.split("|") if item.strip()]
        required = [item.strip() for item in required_raw.split("|") if item.strip()]
        return self.check_draft(draft, forbidden=forbidden, required=required)

    def check_draft(
        self, draft: str, forbidden: List[str], required: List[str]
    ) -> LoreCheckResult:
        errors: List[str] = []
        warnings: List[str] = []

        for token in forbidden:
            if token in draft:
                errors.append(f"检测到禁用设定: {token}")

        for token in required:
            if token not in draft:
                warnings.append(f"未显式出现必备要素: {token}")

        return LoreCheckResult(errors=errors, warnings=warnings)
