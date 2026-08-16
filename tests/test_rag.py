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
    """最小 chroma 集合替身：记录 delete/upsert，模拟 count/get/metadata"""

    def __init__(self, count: int, metadata: dict | None = None):
        self.n = count
        self.metadata = metadata or {}
        self.deleted: list | None = None
        self.upserted: list = []

    def count(self) -> int:
        return self.n

    def get(self) -> dict:
        return {"ids": [f"c{i}" for i in range(self.n)]}

    def delete(self, ids=None):
        self.deleted = ids

    def modify(self, metadata=None):
        self.metadata = metadata or {}

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
    """索引块数与当前一致**且模型版本一致** → 直接复用，不删除不重建"""
    fake = FakeCol(count=2, metadata={"model": rag.EMB_MODEL})
    monkeypatch.setattr(rag, "get_collection", lambda: fake)
    monkeypatch.setattr(rag, "embed_texts", _fake_embeddings)
    rag.build_index([("a", "x" * 50)] * 2)
    assert fake.deleted is None and not fake.upserted, "块数与模型一致应复用"


def test_build_index_rebuilds_on_model_change(monkeypatch):
    """换 embedding 模型（维度相同但向量空间不同）→ 即使块数一致也必须重建"""
    fake = FakeCol(count=2, metadata={"model": "text-embedding-v3"})  # 旧索引：v3
    # 显式指定当前模型 ≠ 旧索引模型：不依赖外部配置（CI 无 .env 时 EMB_MODEL
    # 默认也是 v3，等于旧索引 → 曾错误命中复用分支，本地因 .env 设了 v4 才过）
    monkeypatch.setattr(rag, "EMB_MODEL", "test-emb-v4")
    monkeypatch.setattr(rag, "get_collection", lambda: fake)
    monkeypatch.setattr(rag, "embed_texts", _fake_embeddings)
    rag.build_index([("a", "x" * 50)] * 2)
    assert fake.deleted is not None and len(fake.deleted) == 2, "模型变了应清空重建"
    assert fake.upserted, "应重建新索引"


def test_retrieve_policy_preserves_vector_metadata(monkeypatch):
    monkeypatch.setattr(rag, "load_chunks", lambda: [("policy", "一线城市住宿标准不超过500元/晚")])
    monkeypatch.setattr(rag, "build_index", lambda chunks: object())
    monkeypatch.setattr(
        rag,
        "_search_with_metadata",
        lambda query, col, k=5: [
            (
                0.91,
                {
                    "source": "policy",
                    "section": "三、住宿标准",
                    "version": "2.0",
                    "effective_to": "2099-12-31",
                },
                "一线城市住宿标准不超过500元/晚",
            )
        ],
    )
    context = rag.retrieve_policy("住宿标准")
    assert context.status == "grounded"
    assert context.evidence[0].similarity == 0.91
    assert context.evidence[0].section == "三、住宿标准"
    assert context.evidence[0].version == "2.0"
    assert context.evidence[0].effective_to == "2099-12-31"
    assert context.facts[0].evidence_ids == context.evidence_ids


def test_retrieve_policy_marks_metadata_expired(monkeypatch):
    monkeypatch.setattr(rag, "load_chunks", lambda: [("policy", "一线城市住宿标准不超过500元/晚")])
    monkeypatch.setattr(rag, "build_index", lambda chunks: object())
    monkeypatch.setattr(
        rag,
        "_search_with_metadata",
        lambda query, col, k=5: [
            (0.91, {"source": "policy", "effective_to": "2020-01-01"}, "一线城市住宿标准不超过500元/晚")
        ],
    )
    context = rag.retrieve_policy("住宿标准")
    assert context.status == "stale"
    assert context.facts == ()


def test_search_filters_low_similarity_hits(monkeypatch):
    """低于阈值的命中丢弃：无关文档不拼进上下文（防 LLM 依据无关资料幻觉）"""

    class FakeCol:
        def query(self, query_embeddings, n_results):
            # 三个命中：sim = 1 - dist → 0.6 / 0.4 / 0.1
            return {
                "documents": [["住宿标准块", "报销块", "无关环保块"]],
                "metadatas": [[{"source": "01"}, {"source": "02"}, {"source": "08"}]],
                "distances": [[0.4, 0.6, 0.9]],
            }

    monkeypatch.setattr(rag, "embed_texts", lambda texts: [[0.1] * 4 for _ in texts])
    hits = rag.search("出差住宿标准", FakeCol(), k=5, min_sim=0.35)
    sims = [sim for sim, _, _ in hits]
    assert sims == [0.6, 0.4], f"低相似度 0.1 应被丢弃，实际相似度 {sims}"


def test_policy_facts_cover_deadline_transport_and_approval():
    context = rag.policy_context_from_texts(
        "政策",
        [
            (
                "01_travel_standards",
                "出发前至少3个工作日提交。主管应在1个工作日内完成审批。允许预订：二等座及以下。国内航班：经济舱。",
            ),
            ("02_reimbursement_policy", "出差结束后，应在30个自然日内提交报销申请。"),
        ],
    )
    facts = {(fact.key, fact.value, fact.unit) for fact in context.facts}
    assert ("application_lead_time", 3, "工作日") in facts
    assert ("approval_sla", 1, "工作日") in facts
    assert ("train_seat_standard", "二等座及以下", "座位等级") in facts
    assert ("domestic_flight_cabin", "经济舱", "舱位") in facts
    assert ("reimbursement_deadline", 30, "自然日") in facts


def test_search_all_below_threshold_returns_empty(monkeypatch):
    """全部命中低于阈值 → 返回空（调用方走「资料中没有提到」兜底，不硬答）"""

    class FakeCol:
        def query(self, query_embeddings, n_results):
            return {
                "documents": [["无关环保块"]],
                "metadatas": [[{"source": "08"}]],
                "distances": [[0.85]],  # sim = 0.15 < 0.35
            }

    monkeypatch.setattr(rag, "embed_texts", lambda texts: [[0.1] * 4 for _ in texts])
    assert rag.search("出差住宿标准", FakeCol(), k=5, min_sim=0.35) == []


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
