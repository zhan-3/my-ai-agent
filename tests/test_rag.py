"""RAG 验证：向量检索知识问答

分层：
- 单元层（纯本地零 API）：分块管线（覆盖全部文档、长度上限、小块合并）
- 集成层（-m integration，真实 embedding）：向量检索相关性与排序
"""
import pytest

from xiao_wen import rag


# ---------------- 单元层：分块管线 ----------------

def test_load_chunks_covers_all_8_docs():
    chunks = rag.load_chunks()
    sources = {stem for stem, _ in chunks}
    assert sources == {
        "01_travel_standards", "02_reimbursement_policy", "03_booking_guide",
        "04_faq", "05_emergency_procedures", "06_platform_guide",
        "07_city_specific_tips", "08_environmental_initiatives",
    }, f"应有 8 份文档，实际 {len(sources)} 份"
    assert len(chunks) > 100


def test_chunk_size_within_limit():
    for _, text in rag.load_chunks():
        assert len(text) <= 400, f"块超长：{len(text)} 字"


def test_merge_tiny_chunks_merges_short():
    merged = rag.merge_tiny_chunks([("a", "标题"), ("b", "这是正文内容")], min_len=5)
    assert len(merged) == 1
    assert merged[0][1] == "标题 这是正文内容"


# ---------------- 集成层：向量检索（真实 embedding，-m integration） ----------------

@pytest.mark.integration
def test_vector_search_relevant_and_sorted():
    """真实 embedding 检索：top-1 应命中差旅标准文档，相似度降序"""
    chunks = rag.load_chunks()
    col = rag.build_index(chunks)          # 复用持久化索引，不重复构建
    hits = rag.search("出差住宿标准是什么", col, k=5)
    assert hits, "应有检索结果"
    top_source = hits[0][1]
    assert "01_travel_standards" in top_source, f"top-1 来源：{top_source}"
    assert "住宿" in hits[0][2], "top-1 文档应含关键词"
    sims = [sim for sim, _, _ in hits]
    assert sims == sorted(sims, reverse=True), "相似度应降序"
