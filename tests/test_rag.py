"""RAG 验证（作业加分项 E 点名：对 RAG 进行验证）

分层：
- 单元层（0007 BM25 关键词版，纯本地零 API）：分块管线 + 检索质量
- 集成层（0008 向量版，-m integration，真实 embedding）：向量检索相关性与排序
"""
import importlib.util
import os

import pytest

sys_path = os.path.join(os.path.dirname(__file__), "..", "homework")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(sys_path, filename))
    if spec is None or spec.loader is None:
        raise ImportError(f"加载失败：{filename}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rag07 = _load("rag07", "0007_rag.py")
rag08 = _load("rag08", "0008_rag_vector.py")


# ---------------- 单元层：分块管线（0007 纯本地） ----------------

def test_load_chunks_covers_all_8_docs():
    chunks = rag07.load_chunks()
    sources = {stem for stem, _ in chunks}
    assert sources == {
        "01_travel_standards", "02_reimbursement_policy", "03_booking_guide",
        "04_faq", "05_emergency_procedures", "06_platform_guide",
        "07_city_specific_tips", "08_environmental_initiatives",
    }, f"应有 8 份文档，实际 {len(sources)} 份"
    assert len(chunks) > 100


def test_chunk_size_within_limit():
    for _, text in rag07.load_chunks():
        assert len(text) <= 400, f"块超长：{len(text)} 字"


def test_merge_tiny_chunks_merges_short():
    merged = rag07.merge_tiny_chunks([("a", "标题"), ("b", "这是正文内容")], min_len=5)
    assert len(merged) == 1
    assert merged[0][1] == "标题 这是正文内容"


def test_tokenize_chinese():
    words = rag07.tokenize("出差住宿标准")
    assert "住宿" in words and "出差" in words


# ---------------- 单元层：BM25 检索质量（零 API） ----------------

def test_bm25_policy_search_hits_travel_standards():
    """检索「住宿标准」应命中 01_travel_standards（差旅标准文档）"""
    chunks = rag07.load_chunks()
    tf_list, df, N = rag07.build_bm25(chunks)
    hits = rag07.bm25("出差住宿标准是什么", chunks, tf_list, df, N)
    assert hits, "应有检索结果"
    top_sources = {src for _, src, _ in hits[:3]}
    assert "01_travel_standards" in top_sources, f"top 来源：{top_sources}"
    # 结果按分数降序
    scores = [s for s, _, _ in hits]
    assert scores == sorted(scores, reverse=True)


# ---------------- 集成层：向量检索（真实 embedding，-m integration） ----------------

@pytest.mark.integration
def test_vector_search_relevant_and_sorted():
    """真实 embedding 检索：top-1 应命中差旅标准文档，相似度降序"""
    chunks = rag08.load_chunks()
    col = rag08.build_index(chunks)          # 复用持久化索引，不重复构建
    hits = rag08.search("出差住宿标准是什么", col, k=5)
    assert hits, "应有检索结果"
    top_source = hits[0][1]
    assert "01_travel_standards" in top_source, f"top-1 来源：{top_source}"
    assert "住宿" in hits[0][2], "top-1 文档应含关键词"
    sims = [sim for sim, _, _ in hits]
    assert sims == sorted(sims, reverse=True), "相似度应降序"
