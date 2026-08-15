"""行程运行时验证：在写回长期记忆前检查确定性业务约束。

这个模块是候选行程与持久化之间的唯一验证接缝：LLM 生成候选，验证器决定
候选是否足以写回。它不调用 LLM，也不负责修正候选。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from xiao_wen.trip_planner import ItineraryPlan, TripRequest

_POLICY_CLAIM_RE = re.compile(
    r"(?:政策|标准|规定|报销|限额|上限).{0,30}\d+(?:\.\d+)?\s*(?:元|天|晚|%|百分之)"
    r"|\d+(?:\.\d+)?\s*(?:元|天|晚|%|百分之).{0,20}(?:政策|标准|规定|报销|限额|上限)"
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None


@dataclass
class ValidationResult:
    passed: bool
    warnings: list[ValidationIssue] = field(default_factory=list)
    blocking_issues: list[ValidationIssue] = field(default_factory=list)
    evidence_ids: tuple[str, ...] = ()

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.warnings) and not self.blocking_issues


def validate_trip(
    request: TripRequest,
    plan: ItineraryPlan,
    *,
    policy_text: str = "",
    evidence_ids: tuple[str, ...] = (),
    policy_context: object | None = None,
) -> ValidationResult:
    """校验行程日期、天数和政策数字依据。

    空行程仅作为测试/兼容场景产生 warning；真实调用应在生成结构化行程后验证。
    政策数字只有在本轮提供证据 ID 时才允许通过，避免把 LLM 自己写的数字当成政策。
    """
    warnings: list[ValidationIssue] = []
    blocking: list[ValidationIssue] = []
    days = plan.days

    if not days:
        warnings.append(ValidationIssue("empty_plan", "行程没有逐日安排"))
        return ValidationResult(True, warnings, blocking, evidence_ids)

    if not isinstance(request.duration_days, int) or len(days) != request.duration_days:
        blocking.append(
            ValidationIssue(
                "day_count_mismatch",
                f"请求 {request.duration_days} 天，候选行程有 {len(days)} 天",
                "days",
            )
        )

    try:
        start = date.fromisoformat(request.start_date)
    except ValueError:
        blocking.append(ValidationIssue("invalid_start_date", "出发日期不是有效的 YYYY-MM-DD", "start_date"))
        start = None

    parsed_dates: list[date] = []
    for index, item in enumerate(days):
        try:
            parsed_dates.append(date.fromisoformat(item.date))
        except ValueError:
            blocking.append(ValidationIssue("invalid_plan_date", f"第 {index + 1} 天日期无效", f"days[{index}].date"))

    if start and parsed_dates:
        expected = [start + timedelta(days=i) for i in range(len(parsed_dates))]
        if parsed_dates != expected:
            blocking.append(ValidationIssue("date_not_contiguous", "逐日日期必须从出发日连续排列", "days"))

    policy_claims = [reason for reason in plan.reasons if _POLICY_CLAIM_RE.search(reason)]
    policy_claims.extend(item.hotel for item in days if _POLICY_CLAIM_RE.search(item.hotel))
    policy_facts = getattr(policy_context, "facts", ())
    if policy_claims and not evidence_ids:
        blocking.append(
            ValidationIssue(
                "unsupported_policy_claim",
                "候选行程包含政策数字，但没有绑定本轮政策证据",
                "policy",
            )
        )
    elif policy_claims and not policy_facts:
        blocking.append(
            ValidationIssue(
                "missing_policy_fact",
                "候选行程包含政策数字，但证据中没有可验证的结构化政策事实",
                "policy",
            )
        )
    elif policy_claims and policy_text and not any(str(item) in policy_text for item in policy_claims):
        # 只做保守的文本支持检查；复杂的事实抽取留给后续 PolicyFact 阶段。
        warnings.append(ValidationIssue("policy_claim_not_exactly_matched", "政策表述未能逐字匹配检索片段", "policy"))

    return ValidationResult(not blocking, warnings, blocking, evidence_ids)
