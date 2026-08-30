"""Evidence-backed additive scoring contract for chapter reviews.

The legacy 37 checks remain stable query tags. Review v2 groups them into six
quality domains and one gate-only check so issue volume can no longer drive a
chapter score to zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


RUBRIC_VERSION = "openwrite.review-rubric.v2"
REVIEW_SCHEMA_VERSION = "openwrite.review.v2"
DEFAULT_QUALITY_THRESHOLD = 70.0
DEFAULT_MIN_COVERAGE = 0.80
DEFAULT_CALIBRATION_STATUS = "uncalibrated"


DIMENSION_NAMES: dict[int, str] = {
    1: "OOC检查",
    2: "时间线检查",
    3: "设定冲突",
    4: "战力崩坏",
    5: "数值检查",
    6: "伏笔检查",
    7: "节奏检查",
    8: "文风检查",
    9: "信息越界",
    10: "词汇疲劳",
    11: "利益链断裂",
    12: "年代考据",
    13: "配角降智",
    14: "配角工具人化",
    15: "爽点虚化",
    16: "台词失真",
    17: "流水账",
    18: "知识库污染",
    19: "视角一致性",
    20: "段落等长",
    21: "套话密度",
    22: "公式化转折",
    23: "列表式结构",
    24: "支线停滞",
    25: "弧线平坦",
    26: "节奏单调",
    27: "敏感词检查",
    28: "正传事件冲突",
    29: "未来信息泄露",
    30: "世界规则跨书一致性",
    31: "番外伏笔隔离",
    32: "读者期待管理",
    33: "大纲偏离检测",
    34: "角色还原度",
    35: "世界规则遵守",
    36: "关系动态",
    37: "正典事件一致性",
}


@dataclass(frozen=True)
class CriterionSpec:
    id: str
    name: str
    max_points: float
    legacy_check_ids: tuple[int, ...]


@dataclass(frozen=True)
class DomainSpec:
    id: str
    name: str
    weight: float
    criteria: tuple[CriterionSpec, ...]

    @property
    def legacy_check_ids(self) -> tuple[int, ...]:
        return tuple(check for criterion in self.criteria for check in criterion.legacy_check_ids)


QUALITY_DOMAINS: tuple[DomainSpec, ...] = (
    DomainSpec(
        "coherence",
        "连贯与逻辑",
        20.0,
        (
            CriterionSpec("temporal_continuity", "时间与场景衔接", 5.0, (2,)),
            CriterionSpec("rules_power_numbers", "设定、能力与数值自洽", 5.0, (3, 4, 5, 35)),
            CriterionSpec("knowledge_boundary", "人物知识边界", 5.0, (9,)),
            CriterionSpec("causality_motivation", "行动动机与因果链", 5.0, (11,)),
        ),
    ),
    DomainSpec(
        "character",
        "角色与关系",
        15.0,
        (
            CriterionSpec("character_fidelity", "核心角色还原", 5.0, (1, 34)),
            CriterionSpec("dialogue_behavior", "台词与行为可信度", 5.0, (13, 14, 16)),
            CriterionSpec("relationship_dynamics", "关系变化与互动", 5.0, (36,)),
        ),
    ),
    DomainSpec(
        "plot",
        "情节与承诺",
        20.0,
        (
            CriterionSpec("setup_payoff", "伏笔设置与兑现", 5.0, (6,)),
            CriterionSpec("progression_subplots", "主线推进与支线活性", 5.0, (24, 33)),
            CriterionSpec("arc_change", "章内弧线与状态变化", 5.0, (25,)),
            CriterionSpec("reader_promise", "爽点与读者期待", 5.0, (15, 32)),
        ),
    ),
    DomainSpec(
        "pacing",
        "节奏与场景",
        15.0,
        (
            CriterionSpec("scene_function", "场景功能与推进效率", 5.0, (7,)),
            CriterionSpec("narrative_density", "叙事密度", 5.0, (17,)),
            CriterionSpec("rhythm_variation", "节奏变化", 5.0, (26,)),
        ),
    ),
    DomainSpec(
        "prose",
        "文风与表达",
        15.0,
        (
            CriterionSpec("voice_viewpoint", "叙述声音与视角", 5.0, (8, 19)),
            CriterionSpec("language_precision", "用词准确与自然", 5.0, (10, 21)),
            CriterionSpec("structural_naturalness", "段落与转折结构", 5.0, (20, 22, 23)),
        ),
    ),
    DomainSpec(
        "canon",
        "正典与资料",
        15.0,
        (
            CriterionSpec("research_hygiene", "考据与知识库卫生", 5.0, (12, 18)),
            CriterionSpec("canon_fidelity", "正典事件与信息时序", 5.0, (28, 29, 37)),
            CriterionSpec("cross_work_isolation", "跨书规则与番外隔离", 5.0, (30, 31)),
        ),
    ),
)

GATE_CHECK_IDS: tuple[int, ...] = (27,)
CRITERION_STATUSES = frozenset({"evaluated", "not_applicable", "inconclusive"})
HARD_SEVERITIES = frozenset({"critical", "blocker"})


def _validate_rubric() -> None:
    score_checks = [check for domain in QUALITY_DOMAINS for check in domain.legacy_check_ids]
    all_checks = score_checks + list(GATE_CHECK_IDS)
    if sorted(all_checks) != list(DIMENSION_NAMES):
        raise RuntimeError("review rubric must map every legacy check exactly once")
    if len(all_checks) != len(set(all_checks)):
        raise RuntimeError("review rubric contains duplicate legacy check ids")
    if sum(domain.weight for domain in QUALITY_DOMAINS) != 100.0:
        raise RuntimeError("review domain weights must sum to 100")
    for domain in QUALITY_DOMAINS:
        if sum(criterion.max_points for criterion in domain.criteria) != domain.weight:
            raise RuntimeError(f"criteria for {domain.id} do not sum to its domain weight")


_validate_rubric()


def domain_for_check(check_id: int) -> DomainSpec | None:
    return next((domain for domain in QUALITY_DOMAINS if check_id in domain.legacy_check_ids), None)


def selected_domains(dimensions: Sequence[int] | None) -> tuple[DomainSpec, ...]:
    if dimensions is None:
        return QUALITY_DOMAINS
    selected = {value for value in dimensions if value in DIMENSION_NAMES and value not in GATE_CHECK_IDS}
    domains: list[DomainSpec] = []
    for domain in QUALITY_DOMAINS:
        criteria = tuple(
            CriterionSpec(
                criterion.id,
                criterion.name,
                criterion.max_points,
                tuple(check for check in criterion.legacy_check_ids if check in selected),
            )
            for criterion in domain.criteria
            if selected.intersection(criterion.legacy_check_ids)
        )
        if criteria:
            domains.append(DomainSpec(domain.id, domain.name, sum(item.max_points for item in criteria), criteria))
    return tuple(domains)


def rubric_payload(domains: Sequence[DomainSpec] | None = None) -> dict[str, Any]:
    chosen = tuple(domains or QUALITY_DOMAINS)
    return {
        "version": RUBRIC_VERSION,
        "schema_version": REVIEW_SCHEMA_VERSION,
        "domains": [
            {
                "id": domain.id,
                "name": domain.name,
                "weight": domain.weight,
                "legacy_check_ids": list(domain.legacy_check_ids),
                "criteria": [
                    {
                        "id": criterion.id,
                        "name": criterion.name,
                        "max": criterion.max_points,
                        "legacy_check_ids": list(criterion.legacy_check_ids),
                    }
                    for criterion in domain.criteria
                ],
            }
            for domain in chosen
        ],
        "gate_check_ids": list(GATE_CHECK_IDS),
    }


def _bounded_number(value: Any, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return lower
    return max(lower, min(upper, number))


def normalize_criterion(raw: Mapping[str, Any], spec: CriterionSpec) -> dict[str, Any]:
    status = str(raw.get("status") or "inconclusive").strip().lower()
    if status not in CRITERION_STATUSES:
        status = "inconclusive"
    evidence = [str(value).strip() for value in raw.get("evidence") or [] if str(value).strip()]
    earned = _bounded_number(raw.get("earned"), 0.0, spec.max_points) if status == "evaluated" else 0.0
    if earned > 0 and not evidence:
        status = "inconclusive"
        earned = 0.0
    return {
        "id": spec.id,
        "name": spec.name,
        "status": status,
        "earned": earned,
        "max": spec.max_points,
        "evidence": evidence,
        "rationale": str(raw.get("rationale") or "").strip(),
        "legacy_check_ids": list(spec.legacy_check_ids),
        "issues": [dict(item) for item in raw.get("issues") or [] if isinstance(item, Mapping)],
    }


def normalize_domain(raw: Mapping[str, Any], spec: DomainSpec) -> dict[str, Any]:
    by_id = {
        str(item.get("id") or ""): item
        for item in raw.get("criteria") or []
        if isinstance(item, Mapping)
    }
    criteria = [normalize_criterion(by_id.get(item.id, {}), item) for item in spec.criteria]
    evaluated = [item for item in criteria if item["status"] == "evaluated"]
    potential = [item for item in criteria if item["status"] != "not_applicable"]
    earned = sum(float(item["earned"]) for item in evaluated)
    evaluated_max = sum(float(item["max"]) for item in evaluated)
    potential_max = sum(float(item["max"]) for item in potential)
    return {
        "id": spec.id,
        "name": spec.name,
        "status": "evaluated" if potential_max and evaluated_max == potential_max else (
            "not_applicable" if not potential_max else "inconclusive"
        ),
        "earned": earned,
        "max": evaluated_max,
        "potential_max": potential_max,
        "coverage": evaluated_max / potential_max if potential_max else 1.0,
        "legacy_check_ids": list(spec.legacy_check_ids),
        "criteria": criteria,
    }


def _hard_issue(issue: Mapping[str, Any]) -> bool:
    severity = str(issue.get("review_severity") or issue.get("legacy_severity") or issue.get("severity") or "").lower()
    return severity in HARD_SEVERITIES


def aggregate_review(
    domain_results: Iterable[Mapping[str, Any]],
    issues: Iterable[Mapping[str, Any]],
    *,
    domains: Sequence[DomainSpec] | None = None,
    gates: Iterable[Mapping[str, Any]] = (),
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    production_gate_enabled: bool = False,
    calibration_status: str = DEFAULT_CALIBRATION_STATUS,
) -> dict[str, Any]:
    normalized_calibration = str(calibration_status or DEFAULT_CALIBRATION_STATUS).strip().lower()
    if production_gate_enabled and normalized_calibration != "calibrated":
        raise ValueError("review production gate requires calibrated human thresholds")
    specs = tuple(domains or QUALITY_DOMAINS)
    raw_by_id = {str(item.get("id") or ""): item for item in domain_results}
    normalized_domains = [normalize_domain(raw_by_id.get(spec.id, {}), spec) for spec in specs]
    evaluated_max = sum(float(domain["max"]) for domain in normalized_domains)
    potential_max = sum(float(domain["potential_max"]) for domain in normalized_domains)
    earned = sum(float(domain["earned"]) for domain in normalized_domains)
    quality_score = round(earned / evaluated_max * 100.0, 2) if evaluated_max else None
    coverage = round(evaluated_max / potential_max, 4) if potential_max else 1.0
    normalized_issues = [dict(issue) for issue in issues]
    normalized_gates = [dict(gate) for gate in gates]
    blocked = any(_hard_issue(issue) for issue in normalized_issues) or any(
        str(gate.get("status") or "").lower() in {"blocked", "fail"}
        for gate in normalized_gates
    )
    gate_inconclusive = any(
        str(gate.get("status") or "").lower() == "inconclusive"
        for gate in normalized_gates
    )
    gate_status = "blocked" if blocked else "inconclusive" if gate_inconclusive else "pass"
    execution_status = "failed" if not evaluated_max else "partial" if coverage < 1.0 else "completed"
    if blocked:
        delivery_status = "blocked"
    elif gate_inconclusive or coverage < min_coverage or quality_score is None:
        delivery_status = "inconclusive"
    elif quality_score >= quality_threshold:
        delivery_status = "pass"
    else:
        delivery_status = "revise"
    production_gate_status = (
        delivery_status
        if production_gate_enabled
        else "disabled" if normalized_calibration == "calibrated" else "disabled_uncalibrated"
    )
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "execution_status": execution_status,
        "quality_score": quality_score,
        "earned": round(earned, 2),
        "evaluated_max": round(evaluated_max, 2),
        "potential_max": round(potential_max, 2),
        "coverage": coverage,
        "quality_threshold": float(quality_threshold),
        "min_coverage": float(min_coverage),
        "threshold_calibration": {
            "status": normalized_calibration,
            "production_gate_enabled": bool(production_gate_enabled),
        },
        "production_gate_status": production_gate_status,
        "gate_status": gate_status,
        "delivery_status": delivery_status,
        "domains": normalized_domains,
        "gates": normalized_gates,
        "legacy_check_ids": sorted(
            {check for domain in specs for check in domain.legacy_check_ids} | set(GATE_CHECK_IDS)
        ),
    }


def legacy_adapter(review_v2: Mapping[str, Any]) -> dict[str, Any]:
    score = review_v2.get("quality_score")
    return {
        "score": float(score) if isinstance(score, (int, float)) else 0.0,
        "passed": review_v2.get("delivery_status") == "pass",
    }
