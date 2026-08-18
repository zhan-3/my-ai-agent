"""内置子 Agent：知识问答（多 Agent 架构的子 Agent 实体）

真实现：向量检索知识问答（embedding + chromadb），收口于深模块 xiao_wen.rag。
"""

INTENT = "知识问答"
DESCRIPTION = (
    "用户询问企业知识 → 知识问答：差旅政策、报销规则（材料/时限/发票抬头）、"
    "预订流程（机票/火车票/酒店预订、购票渠道、座位等级、改签、退票、开售时间）、住宿标准、"
    "应急处理（突发情况、航班取消/延误、丢行李、被盗、证件遗失、突发疾病）、"
    "绿色出行（环保、低碳）、晓问商旅平台使用（差旅申请、费用报销、行程管理、在哪订）。"
)

from xiao_wen import rag  # noqa: E402  rag.knowledge_qa(query) -> str


def run(state) -> dict:
    result = rag.answer_policy(state["user_input"])
    context = result.context
    out: dict[str, object] = {
        "answer": result.answer,
        "policy_status": context.status,
        "sources": [
            {
                "evidence_id": source.evidence_id,
                "source": source.source,
                "section": source.section,
                "similarity": source.similarity,
                "text": source.text,
            }
            for source in context.evidence
        ],
    }
    if context.status == "unavailable":
        failure = context.failure or rag.PolicyFailure("search_unavailable", True)
        out["failure"] = {
            "code": "policy_unavailable",
            "message": result.answer,
            "retryable": failure.retryable,
        }
    return out
