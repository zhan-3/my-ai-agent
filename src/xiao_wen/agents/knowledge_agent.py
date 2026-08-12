"""内置子 Agent：知识问答（多 Agent 架构的子 Agent 实体）

真实现：向量检索知识问答（embedding + chromadb），收口于深模块 xiao_wen.rag。
"""
INTENT = "知识问答"
DESCRIPTION = ("用户询问差旅政策、报销规则、预订流程、住宿标准等企业知识 → 知识问答。")

from xiao_wen import rag  # noqa: E402  rag.knowledge_qa(query) -> str


def run(state) -> dict:
    return {"answer": rag.knowledge_qa(state["user_input"])}
