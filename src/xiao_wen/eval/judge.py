"""judge 层（layer 3，LLM-as-judge）：rubric 五条打分，考生考官分离（D4）。

- rubric 抄 spec D4 从 CONTEXT.md 领域规则提炼的五条：任务完成 / 忠实度 / 合规性 /
  简洁性 / 得体性；输出 {score: 1-5, reasons, verdict}，temperature=0 + json_mode。
- judge 模型独立 env（EVAL_JUDGE_MODEL/BASE_URL/API_KEY，缺省回退 DEEPSEEK_*）——
  考生考官分离，防 judge 与被评模型同一偏见源。
- 同用例 N 次多数票（score 众数，平局取高——宽容方向）。
- 截断策略：只留 input/classify/agent 产出/final 关键段，剔除 recent/memory_write
  噪音（省 token + 防上下文泄漏）。
- judge 自身质量：10% 人工复核样本由 run.py 落盘，人机一致率人工比对（漂移监控）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from xiao_wen.llm import get_judge_llm

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
        "差旅要素不全时先索取（缺项提示）而非硬生成；非差旅请求正确归「其他」或婉拒；"
        "住宿遵守差旅政策与用户偏好。违规 ≤2 分。",
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

_JUDGE_SYSTEM = (
    "你是差旅助手「晓问」的回答质量裁判。按以下五条 rubric 逐条打分（1-5），"
    "再给总分（五条平均取整）：\n"
    + "\n".join(f"{i + 1}. {name}：{desc}" for i, (name, desc) in enumerate(RUBRIC))
    + "\n\n总分规则：1=完全不可用，2=明显缺陷，3=基本可用，4=良好，5=优秀。"
    "输出严格 JSON：{{score(1-5), reasons(逐条理由的字符串数组，5 条), verdict(PASS 或 FAIL，score>=4 为 PASS)}}。"
)


class JudgeOutput(BaseModel):
    score: int
    reasons: list[str]
    verdict: str


@dataclass
class JudgeVerdict:
    score: int  # 1-5
    reasons: list[str] = field(default_factory=list)
    verdict: str = "FAIL"


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
        return JudgeVerdict(
            score=out.score,
            reasons=list(out.reasons),
            verdict=out.verdict if out.verdict in ("PASS", "FAIL") else ("PASS" if out.score >= 4 else "FAIL"),
        )
    except Exception:
        return JudgeVerdict(score=0, reasons=["judge 解析失败/模型异常"], verdict="FAIL")


def majority_vote(verdicts: list[JudgeVerdict]) -> JudgeVerdict:
    """N 次多数票：score 众数（平局取高——宽容方向）；reasons 取众数那次。"""
    if not verdicts:
        return JudgeVerdict(score=0, verdict="FAIL")
    scores = [v.score for v in verdicts]
    best = max(scores, key=lambda s: (scores.count(s), s))
    winner = next(v for v in verdicts if v.score == best)
    return JudgeVerdict(score=winner.score, reasons=winner.reasons, verdict=winner.verdict)


def judge_with_votes(events: list[dict], n: int = 3) -> JudgeVerdict:
    """同用例 N 次多数票判定（judge 模型 temperature=0，方差来自模型自身漂移）。"""
    return majority_vote([judge_once(events) for _ in range(n)])


def judge_env_used() -> str:
    """当前 judge 模型来源（日志可追溯）：独立 EVAL_JUDGE_* 或回退 DEEPSEEK_*"""
    if os.environ.get("EVAL_JUDGE_API_KEY"):
        return "EVAL_JUDGE_*"
    return "DEEPSEEK_*（回退，考官与考生同模型）"
