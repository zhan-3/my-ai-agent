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
        "01_travel_standards",
        "02_reimbursement_policy",
        "03_booking_guide",
        "04_faq",
        "05_emergency_procedures",
        "06_platform_guide",
        "07_city_specific_tips",
        "08_environmental_initiatives",
    }, f"应有 8 份文档，实际 {len(sources)} 份"
    assert len(chunks) > 100


def test_chunk_size_within_limit():
    for _, text in rag.load_chunks():
        assert len(text) <= 400, f"块超长：{len(text)} 字"


def test_merge_tiny_chunks_merges_short():
    merged = rag.merge_tiny_chunks([("a", "标题"), ("b", "这是正文内容")], min_len=5)
    assert len(merged) == 1
    assert merged[0][1] == "标题 这是正文内容"


def test_load_chunks_groups_sections_bug004():
    """BUG-004：按章节聚合分块——住宿标准整节一块（含 500/400/300），不再碎成小块"""
    chunks = rag.load_chunks()
    hotel = [t for stem, t in chunks if stem == "01_travel_standards" and "三、住宿标准" in t]
    assert hotel, "应存在整节的住宿标准块"
    assert any("500元/晚" in t and "300元/晚" in t for t in hotel), (
        "住宿标准一线与三线应在同一块内（原实现被切成 5 小块导致检索不到）"
    )


def test_split_compound_query():
    """BUG-004：复合问句按并列连词拆子问句；非复合/过短不误拆"""
    assert rag._split_compound_query("公司差旅住宿和餐补标准是怎样的？") == ["公司差旅住宿", "餐补标准是怎样的？"]
    assert rag._split_compound_query("出差打车和住宿能报销吗") == ["出差打车", "住宿能报销吗"]
    # 非复合（无并列连词）：原句单路
    assert rag._split_compound_query("一线城市的住宿标准是多少") == ["一线城市的住宿标准是多少"]
    # 城市对比句也拆（每城各自检索反而更准），但不产生空/单字符子句
    assert rag._split_compound_query("北京和上海有什么不同") == ["北京", "上海有什么不同"]
    # 拆出过短子句（<2 字）→ 不拆（防误伤）
    assert rag._split_compound_query("北京和") == ["北京和"]


# ---------------- 单元层：embedding 鲁棒性（懒校验 + 重试，全本地） ----------------


def test_import_does_not_require_dashscope(monkeypatch):
    """导入模块不读 env（键值从导入期赋值改为首次调用校验）"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    import importlib

    mod = importlib.reload(rag)
    assert hasattr(mod, "embed_texts")


def test_embed_validation_lists_env_var(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        rag.embed_texts(["查询词"])


def test_embed_retries_transient_failure(monkeypatch):
    """embedding 瞬时失败 → 指数退避重试后成功（不抛给调用方）"""
    import types

    calls = {"n": 0}

    class FakeTextEmbedding:
        @staticmethod
        def call(model=None, input=None, dimension=None):
            calls["n"] += 1
            if calls["n"] < 3:
                return types.SimpleNamespace(status_code=500, code="X", message="限流")
            return types.SimpleNamespace(status_code=200, output={"embeddings": [{"embedding": [0.1] * 1024}]})

    monkeypatch.setattr(rag.dashscope, "TextEmbedding", FakeTextEmbedding)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy")
    vecs = rag.embed_texts(["查询词"])
    assert len(vecs) == 1 and len(vecs[0]) == 1024
    assert calls["n"] == 3  # 2 次重试后成功


# ---------------- 单元层：索引新鲜度（防 stale 索引：块数不一致必须重建） ----------------


class FakeCol:
    """最小 chroma 集合替身：记录 delete/upsert，模拟 count/get"""

    def __init__(self, count: int):
        self.n = count
        self.deleted: list | None = None
        self.upserted: list = []

    def count(self) -> int:
        return self.n

    def get(self) -> dict:
        return {"ids": [f"c{i}" for i in range(self.n)]}

    def delete(self, ids=None):
        self.deleted = ids

    def upsert(self, **kw):
        self.upserted.append(kw)


def _fake_embeddings(texts):
    return [[0.1] * 4 for _ in texts]


def test_build_index_rebuilds_on_count_mismatch(monkeypatch):
    """索引块数与当前文档块不一致（旧残留）→ 清空后重建"""
    fake = FakeCol(count=100)  # 旧索引 100 条（文档已变成 2 块）
    monkeypatch.setattr(rag, "get_collection", lambda: fake)
    monkeypatch.setattr(rag, "embed_texts", _fake_embeddings)
    rag.build_index([("a", "x" * 50)] * 2)
    assert fake.deleted is not None and len(fake.deleted) == 100, "应清空全部旧块"
    assert fake.upserted, "应重建新索引"


def test_build_index_reuses_on_count_match(monkeypatch):
    """索引块数与当前一致 → 直接复用，不删除不重建"""
    fake = FakeCol(count=2)
    monkeypatch.setattr(rag, "get_collection", lambda: fake)
    monkeypatch.setattr(rag, "embed_texts", _fake_embeddings)
    rag.build_index([("a", "x" * 50)] * 2)
    assert fake.deleted is None and not fake.upserted, "块数一致应复用"


# ---------------- 集成层：向量检索（真实 embedding，-m integration） ----------------


@pytest.mark.integration
def test_vector_search_relevant_and_sorted():
    """真实 embedding 检索：top-1 应命中差旅标准文档，相似度降序"""
    chunks = rag.load_chunks()
    col = rag.build_index(chunks)  # 复用持久化索引，不重复构建
    hits = rag.search("出差住宿标准是什么", col, k=5)
    assert hits, "应有检索结果"
    top_source = hits[0][1]
    assert "01_travel_standards" in top_source, f"top-1 来源：{top_source}"
    assert "住宿" in hits[0][2], "top-1 文档应含关键词"
    sims = [sim for sim, _, _ in hits]
    assert sims == sorted(sims, reverse=True), "相似度应降序"
