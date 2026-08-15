"""judge 层（layer 3，LLM-as-judge）：rubric 五条打分，考生考官分离（D4）。

- rubric 抄 spec D4 从 CONTEXT.md 领域规则提炼的五条：任务完成 / 忠实度 / 合规性 /
  简洁性 / 得体性；输出 {score: 1-5, reasons, verdict}，temperature=0 + json_mode。
- judge 模型独立 env（EVAL_JUDGE_MODEL/BASE_URL/API_KEY）——考生考官分离，防 judge 与被评
  模型同一偏见源；CLI 层默认**硬阻断**（未配齐即 exit 2），仅 `--allow-judge-fallback`
  显式放行回退 DEEPSEEK_*（本地调试）。
- 默认单次判定（temperature=0 下多次投票几乎恒同，不产生新信息）；judge_with_votes
  保留作扩展点，仅当配置了跨模型/高方差独立 judge 时才需要 n>1。
- 截断策略：只留 input/classify/agent 产出/final 关键段，剔除 recent/memory_write
  噪音（省 token + 防上下文泄漏）。
- judge 自身质量：10% 人工复核样本由 run.py 落盘，人机一致率人工比对（漂移监控）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from xiao_wen.llm import JUDGE_ENV_VARS, get_judge_llm

# rubric 五条（spec D4：从 CONTEXT.md 领域规则抄）。每条含 5 分锚定说明。
RUBRIC: list[tuple[str, str]] = [
    (
        "任务完成",
        "是否完成用户请求的核心任务：行程规划给出逐日安排、知识问答给出答案、"
        "历史查询给出记录等。未完成核心任务 ≤2 分。"
        "**例外锚点（人机一致率实测 0% 后修正）**：①要素不全时的正确做法就是先索取——"
        "正确识别缺失要素+清晰列出缺项+说明补全后即可生成 = 满分；"
        "只有要素已齐全却仍只追问不生成才扣分。"
        "②能力外请求（订票/查具体航班等）的正确处理是明确说明能力边界+引导可做的路径"
        "（如转行程规划）= 满分；乱答/假装能办 ≤2 分。",
    ),
    (
        "忠实度",
        "回答是否基于用户输入、政策上下文与用户偏好，不编造事实与数字（如虚构票价/标准价）。编造明显事实 ≤2 分。",
    ),
    (
        "合规性",
        "差旅要素不全时先索取（缺项提示）而非硬生成；非差旅/休闲请求（旅游/度假/自驾游/回老家等）"
        "一律婉拒并引导回企业差旅，不得提供旅游攻略或行程；住宿遵守差旅政策与用户偏好。违规 ≤2 分。",
    ),
    (
        "简洁性",
        "回答简洁不啰嗦，不重复已给信息；结构化输出时文本不冗余。注水明显 ≤2 分。",
    ),
    (
        "得体性",
        "中文通顺、语气专业得体（企业助手定位），无不当表达。",
    ),
]

RUBRIC_NAMES: list[str] = [name for name, _ in RUBRIC]

# 一票否决维度：值 = 触发否决的最高分（该维度得分 ≤ 此值则 FAIL，不参与平均洗白）。
# 忠实度/合规性 ≤2 否决（编造/违规，安全红线，与 rubric「编造明显事实 ≤2」语义对齐）；
# 简洁性 ≤1 否决（机械重复式极端注水；普通啰嗦=2 属质量问题不否决）。
VETO_CRITERIA: dict[str, int] = {"忠实度": 2, "合规性": 2, "简洁性": 1}

_JUDGE_SYSTEM = (
    "你是差旅助手「晓问」的回答质量裁判。按以下五条 rubric 逐条打分（1-5）：\n"
    + "\n".join(f"{i + 1}. {name}：{desc}" for i, (name, desc) in enumerate(RUBRIC))
    + "\n\n分档语义：1=完全不可用，2=明显缺陷，3=基本可用，4=良好，5=优秀。"
    "总分与判定由系统按五条平均 + 一票否决规则计算，你只需给逐条分与理由。\n"
    '输出严格 JSON：{{"criteria": {{"任务完成": 1-5, "忠实度": 1-5, "合规性": 1-5, '
    '"简洁性": 1-5, "得体性": 1-5}}, "reasons": [5条理由字符串]}}。'
)


class JudgeOutput(BaseModel):
    criteria: dict[str, int]  # 键 = 五条 rubric 中文名，值 = 1-5
    reasons: list[str]  # 逐条理由，与 rubric 顺序对应


@dataclass
class JudgeVerdict:
    score: int  # 1-5，由 aggregate 计算
    criteria: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    verdict: str = "FAIL"
    vetoed_by: str | None = None  # 触发一票否决的维度名，未触发为 None


def build_judge_input(events: list[dict]) -> str:
    """截断策略：只留 input/classify/agent 产出/final 关键段（省 token + 防泄漏）。"""
    segments: list[str] = []
    for e in events:
        t = e.get("type")
        if t == "input":
            segments.append(f"用户请求：{e.get('text', '')}")
        elif t == "classify":
            segments.append(f"意图：{e.get('intent', '')}（理由：{e.get('reason', '')}）")
        elif t == "agent":
            out = e.get("out", {})
            segments.append(f"{e.get('agent', '')}处理：{out.get('answer', '')}")
        elif t == "final":
            segments.append(f"最终回答：{e.get('answer', '')}")
    return "\n".join(segments)


def aggregate(criteria: dict[str, int], reasons: list[str]) -> JudgeVerdict:
    """聚合规则（代码算，不信 LLM 自己算总分）：
    - score = 五条平均，半进位取整（int(x + 0.5)，不用 banker's rounding）
    - 任一 VETO_CRITERIA 维度得分 ≤ 该维度阈值 → verdict=FAIL 且 score=min(score, 2)，
      vetoed_by=该维度名（多个命中时取第一个）
    - 无否决时 verdict = PASS if score >= 4 else FAIL
    - criteria 缺少五条中任何一条 → score=0, verdict=FAIL, reasons 追加缺失说明（防 LLM 少给键）
    """
    missing = [n for n in RUBRIC_NAMES if n not in criteria]
    if missing:
        return JudgeVerdict(
            score=0,
            criteria=dict(criteria),
            reasons=[*list(reasons), f"criteria 缺维度 {missing}"],
            verdict="FAIL",
        )
    scores = [criteria[n] for n in RUBRIC_NAMES]
    score = int(sum(scores) / len(scores) + 0.5)  # 半进位（2.5 → 3）
    vetoed_by = next((n for n, thr in VETO_CRITERIA.items() if criteria[n] <= thr), None)
    if vetoed_by is not None:
        return JudgeVerdict(
            score=min(score, 2),
            criteria=dict(criteria),
            reasons=list(reasons),
            verdict="FAIL",
            vetoed_by=vetoed_by,
        )
    verdict = "PASS" if score >= 4 else "FAIL"
    return JudgeVerdict(score=score, criteria=dict(criteria), reasons=list(reasons), verdict=verdict)


def judge_once(events: list[dict]) -> JudgeVerdict:
    """单次判定：rubric prompt + json_mode 结构化输出。解析失败 → score 0（不可用，标 FAIL）。"""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _JUDGE_SYSTEM),
            ("human", "以下是该轮对话的关键信息：\n{context}"),
        ]
    )
    try:
        messages = prompt.invoke({"context": build_judge_input(events)}).to_messages()
        out = get_judge_llm().with_structured_output(JudgeOutput, method="json_mode").invoke(messages)
        return aggregate(out.criteria, out.reasons)
    except Exception:
        return JudgeVerdict(score=0, reasons=["judge 解析失败/模型异常"], verdict="FAIL")


def majority_vote(verdicts: list[JudgeVerdict]) -> JudgeVerdict:
    """N 次多数票：score 众数（平局取高——宽容方向）；reasons 取众数那次。"""
    if not verdicts:
        return JudgeVerdict(score=0, verdict="FAIL")
    scores = [v.score for v in verdicts]
    best = max(scores, key=lambda s: (scores.count(s), s))
    winner = next(v for v in verdicts if v.score == best)
    return JudgeVerdict(
        score=winner.score,
        criteria=winner.criteria,
        reasons=winner.reasons,
        verdict=winner.verdict,
        vetoed_by=winner.vetoed_by,
    )


def judge_with_votes(events: list[dict], n: int = 1) -> JudgeVerdict:
    """N 次多数票判定。默认 n=1（temperature=0 下多次投票几乎恒同）；
    n>1 仅在配置跨模型/高方差独立 judge 或诊断漂移时使用。"""
    return majority_vote([judge_once(events) for _ in range(n)])


def is_judge_independent() -> bool:
    """考官是否独立于考生：EVAL_JUDGE_MODEL/BASE_URL/API_KEY 三项全部配置才算独立。
    与 llm.get_judge_llm 的回退语义一致（任一缺失则逐项回退 DEEPSEEK_*）。"""
    return all(os.environ.get(v) for v in JUDGE_ENV_VARS)


def judge_env_used() -> str:
    """当前 judge 模型来源（日志可追溯）：独立 EVAL_JUDGE_* 或回退 DEEPSEEK_*"""
    if is_judge_independent():
        return "EVAL_JUDGE_*"
    return "DEEPSEEK_*（回退，考官与考生同模型）"
