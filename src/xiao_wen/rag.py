"""RAG 模块：向量检索升级版知识问答（dashscope text-embedding-v3 + Chroma 余弦检索）
跑法：uv run python -m xiao_wen.rag
依赖：.env 里 DASHSCOPE_API_KEY（阿里云百炼）；numpy / chromadb（已装）

方案演进：早期用关键词检索（jieba 分词 + BM25）暴露语义天花板
（「延长出差时间」误命中环保文档）后，换成向量检索；现行方案即向量版。

设计要点：
- 索引构建一次性：8 份文档分块 → 批量 embedding → Chroma 磁盘持久化
- 查询：问题 embedding → 余弦相似度 top-k（向量检索，无需查询改写）
- 生成：命中块拼进提示词 → LLM 依据资料回答
"""

import hashlib
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from http import HTTPStatus
from typing import Literal

import chromadb
import dashscope
from langchain_core.prompts import ChatPromptTemplate

from xiao_wen import ROOT, llm
from xiao_wen.config import EMBED_ENV_VAR, load_settings
from xiao_wen.stability import with_retry

# 项目根目录（单一来源：xiao_wen.ROOT，C7 收敛）
DOCS_DIR = ROOT / "docs" / "documents"
CHROMA_DIR = ROOT / "data" / "chroma"
# embedding 模型可配置（.env 覆盖；换模型必须重建索引，见 build_index 模型版本检查）
EMB_MODEL = "text-embedding-v3"
EMB_DIM = 1024
BATCH = 10  # 每次 API 调用批量 embedding 条数
ANN_CANDIDATE_MULTIPLIER = 4  # HNSW 先扩大近似候选池，再按实际距离截取最终 top-k
COLLECTION = "travel_docs"
CHROMA_LOCK = CHROMA_DIR.parent / "chroma.lock"


@contextmanager
def _chroma_lock():
    """跨进程串行化 Chroma 访问，避免 Rust HNSW/SQLite 并发访问导致 native 崩溃。"""
    import fcntl

    CHROMA_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with CHROMA_LOCK.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


# 检索相似度阈值：低于此值的命中视为语义无关丢弃（防无关文档拼进提示词引发幻觉）。
# text-embedding-v3 余弦相似度：相关文档通常 >0.4，无关 <0.3；可 .env 用 RAG_MIN_SIM 覆盖。
MIN_SIM = 0.35


def _embedding_config() -> tuple[str, int]:
    settings = load_settings()
    return settings.dashscope_emb_model or EMB_MODEL, settings.embedding_dimension(EMB_DIM)


def _min_similarity() -> float:
    return load_settings().minimum_similarity(MIN_SIM)


@dataclass(frozen=True)
class Evidence:
    """一条可追溯的检索证据；ID 对同一来源和文本稳定。"""

    evidence_id: str
    source: str
    text: str
    similarity: float
    section: str | None = None
    version: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None


@dataclass(frozen=True)
class PolicyFact:
    """由可见政策原文确定性抽取的事实；每个事实必须绑定证据。"""

    key: str
    value: int | float | str
    unit: str
    scope: dict[str, str]
    evidence_ids: tuple[str, ...]


PolicyStatus = Literal["grounded", "not_found", "unavailable", "stale", "ambiguous"]


@dataclass(frozen=True)
class PolicyContext:
    """本轮政策检索快照，供行程生成和运行时验证共同使用。"""

    query: str
    evidence: tuple[Evidence, ...]
    status: PolicyStatus = "not_found"
    facts: tuple[PolicyFact, ...] = ()
    snapshot_id: str = ""
    failure: "PolicyFailure | None" = None

    @property
    def has_stale_evidence(self) -> bool:
        today = date.today()
        for item in self.evidence:
            if item.effective_to:
                try:
                    if today > date.fromisoformat(item.effective_to):
                        return True
                except ValueError:
                    return True
        return False

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)

    @property
    def text(self) -> str:
        return "\\n\\n".join(item.text for item in self.evidence)


PolicyFailureCode = Literal["documents_unavailable", "index_unavailable", "search_unavailable"]


@dataclass(frozen=True)
class PolicyFailure:
    """政策依赖故障；调用方只消费稳定代码，不解析 adapter 异常文本。"""

    code: PolicyFailureCode
    retryable: bool


@dataclass(frozen=True)
class PolicyAnswer:
    answer: str
    context: PolicyContext


def _extract_policy_facts(evidence: tuple[Evidence, ...]) -> tuple[PolicyFact, ...]:
    """从已检索原文提取当前产品所需的有限政策事实，不从模型输出提取。"""
    facts: list[PolicyFact] = []
    evidence_ids = tuple(item.evidence_id for item in evidence)
    for item in evidence:
        text = item.text
        patterns = [
            ("hotel_rate", r"一线城市.*?不超过\s*(\d+)\s*元/晚", "元/晚", {"city_tier": "一线"}),
            ("hotel_rate", r"二线城市.*?不超过\s*(\d+)\s*元/晚", "元/晚", {"city_tier": "二线"}),
            ("hotel_rate", r"三线(?:及以下)?城市.*?不超过\s*(\d+)\s*元/晚", "元/晚", {"city_tier": "三线"}),
            ("breakfast_rate", r"早餐.*?不超过\s*(\d+)\s*元/餐", "元/餐", {}),
            ("meal_rate", r"(?:午餐和晚餐|午餐|晚餐).*?每餐不超过\s*(\d+)\s*元", "元/餐", {}),
            ("application_lead_time", r"出发前至少\s*(\d+)\s*个工作日提交", "工作日", {}),
            ("approval_sla", r"主管应在\s*(\d+)\s*个工作日内完成审批", "工作日", {}),
            ("reimbursement_deadline", r"出差结束后.*?在\s*(\d+)\s*个自然日内提交报销", "自然日", {}),
            ("long_trip_approval_days", r"长期出差（超过\s*(\d+)\s*天）", "天", {}),
            ("meal_entertainment_approval", r"超过\s*(\d+)\s*元需要部门主管审批", "元", {}),
            ("train_seat_standard", r"允许预订：([^。\n]+)", "座位等级", {}),
            ("domestic_flight_cabin", r"国内航班：([^。\n]+)", "舱位", {}),
            ("taxi_reimbursement_scope", r"允许使用场景：([^。\n]+)", "场景", {}),
        ]
        for key, pattern, unit, scope in patterns:
            match = re.search(pattern, text)
            if match:
                raw_value = match.group(1).strip()
                value: int | str = int(raw_value) if raw_value.isdigit() else raw_value
                facts.append(PolicyFact(key, value, unit, scope, evidence_ids))
    return tuple(facts)


def policy_context_from_texts(query: str, texts: list[tuple[str, str]]) -> PolicyContext:
    evidence_items = []
    for source, text in texts:
        expires = re.search(r"(?:有效期至|生效至|截止日期)\s*[:：]?\s*(\d{4}-\d{2}-\d{2})", text)
        version = re.search(r"(?:版本|v)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)*)", text, re.IGNORECASE)
        evidence_items.append(
            Evidence(
                _evidence_id(source, text),
                source,
                text,
                0.0,
                version=version.group(1) if version else None,
                effective_to=expires.group(1) if expires else None,
            )
        )
    evidence = tuple(evidence_items)
    facts = _extract_policy_facts(evidence)
    conflicting_keys = {
        (fact.key, tuple(sorted(fact.scope.items())))
        for fact in facts
        if sum(other.key == fact.key and other.scope == fact.scope and other.value != fact.value for other in facts)
    }
    status: PolicyStatus = "not_found" if not evidence else ("ambiguous" if conflicting_keys else "grounded")
    exposed_facts = () if conflicting_keys else facts
    snapshot = hashlib.sha256("\\n".join(item.evidence_id for item in evidence).encode()).hexdigest()[:16]
    if status == "grounded" and any(item.effective_to for item in evidence):
        status = "stale" if PolicyContext(query, evidence).has_stale_evidence else status
    return PolicyContext(
        query=query,
        evidence=evidence,
        facts=exposed_facts if status == "grounded" else (),
        status=status,
        snapshot_id=f"policy-{snapshot}",
    )


# ---- 1. LLM（知识生成，走单一接缝，懒构建）----
# ---- 2. dashscope embedding（懒校验 + 重试：导入不读 env，首次调用才校验）----
_EMBED_ENV_VAR = EMBED_ENV_VAR


def _validate_dashscope() -> None:
    dashscope.api_key = load_settings().require_embedding_key()


@with_retry(retries=2, base_delay=0.5)
def _embed_batch(batch: list[str]):
    """单批 embedding（指数退避重试，容忍免费 API 抖动）"""
    model, dimension = _embedding_config()
    resp = dashscope.TextEmbedding.call(model=model, input=batch, dimension=dimension)
    if resp.status_code != HTTPStatus.OK:
        raise RuntimeError(f"embedding 失败: {resp.code} {resp.message}")
    return resp


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量调用 text-embedding-v3，返回归一化向量列表（首次调用校验 DASHSCOPE_API_KEY）"""
    _validate_dashscope()
    vecs: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]
        resp = _embed_batch(batch)
        vecs.extend(e["embedding"] for e in resp.output["embeddings"])
        time.sleep(0.2)  # 限速，避免触发频率限制
    return vecs


# ---- 3. 分块（按「一、二、三」章节聚合，标题和内容同块）----
_SECTION_RE = "一二三四五六七八九十"


def _is_section_header(line: str) -> bool:
    """章节标题行：如「一、差旅申请流程」（标题行/正文行不拆分）"""
    line = line.strip()
    if len(line) < 2:
        return False
    return line[0] in _SECTION_RE and (line[1] in "、．." or line[1] in _SECTION_RE)


def load_chunks(max_len: int = 400):
    """分块：按章节聚合（一、交通标准 → 整节一块），超长按句号截断

    BUG-004 修复：原先按空行切成很多碎片（如「三、住宿标准」被切成
    一线/二线/三线/特殊地区/住宿要求 5 小块），导致「住宿标准是多少」
    这类问题 top-5 检索不到完整标准（答出「未提及」）。按章节聚合后
    一节一个语义完整的块，检索命中率稳定。
    """
    chunks = []
    for path in sorted(DOCS_DIR.glob("*.txt")):
        para: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if _is_section_header(line) and para:
                chunks.append((path.stem, " ".join(para)))
                para = []
            para.append(line)
        if para:
            chunks.append((path.stem, " ".join(para)))
    final = []
    for stem, chunk in chunks:
        rest = chunk
        while len(rest) > max_len:
            cut = rest.rfind("。", 0, max_len)
            if cut > 0:
                final.append((stem, rest[: cut + 1]))
                rest = rest[cut + 1 :]
            else:
                # 无句号可断：按 max_len 硬切（rest[:max_len+1] 会超限——BUG-004 顺带修复）
                final.append((stem, rest[:max_len]))
                rest = rest[max_len:]
        if rest:
            final.append((stem, rest))
    return final


def _section_from_text(text: str) -> str | None:
    match = re.search(r"([一二三四五六七八九十]+)、[^ ]+", text)
    return match.group(0) if match else None


def _chunk_metadata(stem: str, text: str) -> dict[str, str]:
    """生成与 chunk 一起写入向量库的可追溯元数据。"""
    expires = re.search(r"(?:有效期至|生效至|截止日期)\s*[:：]?\s*(\d{4}-\d{2}-\d{2})", text)
    version = re.search(r"(?:版本|v)\s*[:：]?\s*([0-9]+(?:\.[0-9]+)*)", text, re.IGNORECASE)
    return {
        "source": stem,
        "section": _section_from_text(text) or "",
        "version": version.group(1) if version else "",
        "effective_to": expires.group(1) if expires else "",
        "content_hash": hashlib.sha256(text.encode()).hexdigest()[:16],
    }


def _chunks_signature(chunks) -> str:
    payload = "\n".join(f"{stem}:{_chunk_metadata(stem, text)}:{text}" for stem, text in chunks)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def merge_tiny_chunks(chunks, min_len: int = 20):
    merged = []
    i, n = 0, len(chunks)
    while i < n:
        stem, text = chunks[i]
        if len(text) < min_len and i + 1 < n:
            merged.append((stem, text + " " + chunks[i + 1][1]))
            i += 2
        else:
            merged.append((stem, text))
            i += 1
    return merged


# ---- 4. 向量库索引（chromadb 持久化 + HNSW 近似最近邻）----
def get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})  # 余弦距离


def build_index(chunks):
    """文档块 → dashscope embedding → 存入 chroma（磁盘持久化）

    整个打开/检查/重建过程持有跨进程锁，避免 Web 进程和 CLI/测试同时触碰
    Chroma 的 Rust 索引。"""
    with _chroma_lock():
        return _build_index_locked(chunks)


def _build_index_locked(chunks):
    """在 `_chroma_lock` 内执行索引检查和构建。

    换 embedding 模型或文档内容后清空并重建索引，避免复用过期向量。
    """
    col = get_collection()
    meta = getattr(col, "metadata", None) or {}
    existing = col.count()
    signature = _chunks_signature(chunks)
    model, _ = _embedding_config()
    if existing == len(chunks) and meta.get("model") == model and meta.get("chunks_signature", signature) == signature:
        print(f"（复用 chroma 持久化索引，{existing} 条 · {model}）")
        return col
    if existing:
        print(f"（索引过期：现有 {existing} 条 / 模型 {meta.get('model')} ≠ {model}，清空重建…）")
        col.delete(ids=col.get()["ids"])
    print(f"（构建 chroma 索引：{len(chunks)} 块 × {model}，首次 1-2 分钟…）")
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        vecs = embed_texts([t for _, t in batch])
        col.upsert(
            ids=[f"c{i + j}" for j in range(len(batch))],
            embeddings=vecs,
            documents=[t for _, t in batch],
            metadatas=[_chunk_metadata(stem, text) for stem, text in batch],
        )
        time.sleep(0.2)
    col.modify(metadata={"model": model, "chunks_signature": signature})  # 不带 hnsw:space，Chroma 拒绝修改距离函数
    return col


def _split_compound_query(query: str) -> list[str]:
    """复合问句拆分：按并列连词（和/与/以及/、）切分，供多路检索

    BUG-004：单路检索一个 embedding 混合多个主题时，每主题都排不进 top-k
    （如「住宿和餐补标准」→ 住宿标准块 rank 11）。拆成子问句各自检索，
    再合并去重，答案稳定完整。
    防误拆：切出的子句过短（<2 字）或切不出（仅 1 段）时返回原句单路。
    """
    parts = [p.strip() for p in re.split(r"[和与及、以及]+", query) if p.strip()]
    if len(parts) < 2 or any(len(p) < 2 for p in parts):
        return [query]
    return parts


def _search_with_metadata(query: str, col, k: int = 5, min_sim: float | None = None):
    """问题 embedding → chroma 余弦检索 top-k（HNSW 近似最近邻）

    查询也必须持有跨进程锁；仅锁建库不能阻止另一个进程同时 query。"""
    with _chroma_lock():
        return _search_with_metadata_locked(query, col, k, min_sim)


def _search_with_metadata_locked(query: str, col, k: int = 5, min_sim: float | None = None):
    """在 `_chroma_lock` 内执行查询并按相似度返回 top-k。"""
    threshold = _min_similarity() if min_sim is None else min_sim
    subs = _split_compound_query(query)
    per = max(1, -(-k // len(subs)))  # 每子问句席位：k 按主题数均分向上取整
    candidates = per * ANN_CANDIDATE_MULTIPLIER
    out: dict[str, tuple[float, dict, str]] = {}
    for sub in subs:
        qv = embed_texts([sub])[0]
        res = col.query(query_embeddings=[qv], n_results=candidates)
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True):
            sim = 1 - dist  # 余弦距离 → 相似度
            out.setdefault(doc, (sim, meta, doc))
    ranked = sorted(out.values(), key=lambda t: t[0], reverse=True)
    return [t for t in ranked if t[0] >= threshold][:k]


def search(query: str, col, k: int = 5, min_sim: float | None = None):
    """兼容旧接缝：返回 (similarity, source, text)。"""
    return [(sim, meta["source"], text) for sim, meta, text in _search_with_metadata(query, col, k, min_sim)]


# ---- 5. 增强 + 生成 ----
knowledge_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是晓问公司的差旅政策顾问。严格依据【参考资料】回答用户问题。
规则：
- 只能依据资料中的内容回答；资料没有提到的，明确说「资料中没有提到」
- 回答用中文，简洁准确，可以直接引用原文数据（如金额、天数、标准）
- 不要编造政策""",
        ),
        ("human", "【参考资料】\n{context}\n\n问题：{query}"),
    ]
)


@lru_cache
def _knowledge_model():
    return knowledge_prompt | llm.get_llm()


def _evidence_id(source: str, text: str) -> str:
    digest = hashlib.sha256(f"{source}\\n{text}".encode()).hexdigest()[:16]
    return f"ev-{digest}"


class PolicyProvider:
    """政策检索深模块：分类 adapter 故障并只返回稳定的领域结果。"""

    def __init__(self, *, chunk_loader=None, index_builder=None, searcher=None) -> None:
        self._chunk_loader = chunk_loader
        self._index_builder = index_builder
        self._searcher = searcher

    @staticmethod
    def _unavailable(query: str, code: PolicyFailureCode, *, retryable: bool) -> PolicyContext:
        return PolicyContext(
            query=query,
            evidence=(),
            status="unavailable",
            failure=PolicyFailure(code=code, retryable=retryable),
        )

    def retrieve(self, query: str, k: int = 5) -> PolicyContext:
        try:
            chunks = self._chunk_loader() if self._chunk_loader is not None else merge_tiny_chunks(load_chunks())
        except Exception:
            return self._unavailable(query, "documents_unavailable", retryable=False)
        if not chunks:
            return self._unavailable(query, "documents_unavailable", retryable=False)
        try:
            col = self._index_builder(chunks) if self._index_builder is not None else build_index(chunks)
        except Exception:
            return self._unavailable(query, "index_unavailable", retryable=True)

        queries = [query]
        if any(word in query for word in ("住宿", "开会", "出差", "行程", "北京", "上海")):
            queries.extend(
                ("公司差旅住宿标准 一线城市 不超过 元/晚", "公司差旅交通标准 高铁 二等座", "公司差旅报销标准 审批")
            )
        try:
            hit_map: dict[tuple[object, object], tuple[float, dict, str]] = {}
            for search_query in queries:
                search = self._searcher or _search_with_metadata
                for hit in search(search_query, col, k=k):
                    key = (hit[1].get("source"), hit[2])
                    hit_map.setdefault(key, hit)
            hits = list(hit_map.values())[: max(k, 8)]
        except Exception:
            return self._unavailable(query, "search_unavailable", retryable=True)

        text_context = policy_context_from_texts(query, [(hit[1]["source"], hit[2]) for hit in hits])
        evidence = tuple(
            Evidence(
                item.evidence_id,
                item.source,
                item.text,
                hit[0],
                section=hit[1].get("section"),
                version=hit[1].get("version"),
                effective_from=hit[1].get("effective_from"),
                effective_to=hit[1].get("effective_to"),
            )
            for item, hit in zip(text_context.evidence, hits, strict=True)
        )
        status = text_context.status
        if status == "grounded" and PolicyContext(query, evidence).has_stale_evidence:
            status = "stale"
        return PolicyContext(
            query=text_context.query,
            evidence=evidence,
            facts=_extract_policy_facts(evidence) if status == "grounded" else (),
            status=status,
            snapshot_id=text_context.snapshot_id,
        )


def retrieve_policy(query: str, k: int = 5) -> PolicyContext:
    """兼容入口：政策检索统一委托 ``PolicyProvider``。"""
    return PolicyProvider().retrieve(query, k=k)


def _source_evidence(query: str, col, source: str, k: int = 3) -> tuple[Evidence, ...]:
    """从指定文档来源取证据，用于行程生成的主动知识注入。

    先扩大候选集再按 source 过滤，避免把「城市/应急/环保」三个主题混在一个
    top-k 里导致某一主题霸榜。该函数仍复用同一向量索引，不另建知识库。
    """
    hits = _search_with_metadata(query, col, k=20)
    selected = [hit for hit in hits if hit[1].get("source") == source][:k]
    return tuple(
        Evidence(
            _evidence_id(source, text),
            source,
            text,
            sim,
            section=meta.get("section"),
            version=meta.get("version"),
            effective_to=meta.get("effective_to"),
        )
        for sim, meta, text in selected
    )


def retrieve_guidance(city: str) -> dict[str, tuple[Evidence, ...]]:
    """主动知识检索：按目的地为行程生成收集城市、应急和绿色出行提示。

    返回证据而非 LLM 文本，调用方可同时把内容注入 prompt 并保留来源。
    任一 embedding/索引异常均降级为空，不阻塞行程规划。
    """
    try:
        chunks = merge_tiny_chunks(load_chunks())
        col = build_index(chunks)
        return {
            "city_tips": _source_evidence(f"{city} 出差交通住宿注意事项", col, "07_city_specific_tips", k=2),
            "emergency_tips": _source_evidence("出差紧急情况处理流程 联系方式", col, "05_emergency_procedures", k=1),
            "green_tips": _source_evidence("差旅绿色出行 高铁 公共交通 环保", col, "08_environmental_initiatives", k=1),
        }
    except Exception:
        return {"city_tips": (), "emergency_tips": (), "green_tips": ()}


def search_texts(query: str, k: int = 5) -> list[str]:
    """纯检索（无 LLM）：返回命中文本段列表（空 = 无命中/索引不可用）。

    供 collect-then-compose 收集者（行程规划等）注入上游上下文：
    只要政策原文，不需要知识问答 agent 的一轮 LLM 生成。索引/网络异常降级空列表，不阻塞。
    """
    try:
        chunks = merge_tiny_chunks(load_chunks())
        col = build_index(chunks)
        hits = _search_with_metadata(query, col, k=k)
        return [text for _, _, text in hits]
    except Exception:
        return []


def answer_policy(query: str) -> PolicyAnswer:
    """知识问答领域结果：检索状态与答案、证据保持同一个快照。"""
    context = retrieve_policy(query, k=5)
    if context.status == "unavailable":
        return PolicyAnswer("⚠️ 政策服务暂时不可用，请稍后重试。", context)
    if context.status == "not_found":
        return PolicyAnswer("资料中没有找到相关内容。", context)
    if context.status == "ambiguous":
        return PolicyAnswer("检索到的政策资料存在冲突，暂不能给出确定结论，请联系差旅管理员确认。", context)
    if context.status == "stale":
        return PolicyAnswer("检索到的政策资料已过有效期，暂不能作为当前标准，请联系差旅管理员确认。", context)
    from xiao_wen.stability import logger

    logger.info(
        "RAG 检索 top-%d 来源：%s（问题：%s）",
        len(context.evidence),
        [e.source for e in context.evidence],
        query,
    )
    prompt_context = "\n\n".join(f"--- 来源 {item.source} ---\n{item.text}" for item in context.evidence)
    answer = _knowledge_model().invoke({"context": prompt_context, "query": query}).content
    return PolicyAnswer(answer, context)


def knowledge_qa_with_sources(query: str) -> tuple[str, tuple[Evidence, ...]]:
    """兼容旧调用：新 Agent 应消费 ``answer_policy`` 的状态。"""
    result = answer_policy(query)
    return result.answer, result.context.evidence


def knowledge_qa(query: str) -> str:
    """兼容旧调用：只返回答案文本。"""
    answer, sources = knowledge_qa_with_sources(query)
    if not sources:
        return answer
    source_names = "、".join(dict.fromkeys(source.source for source in sources))
    return f"{answer}\n\n依据：{source_names}"


if __name__ == "__main__":
    tests = [
        "出差住宿标准是什么？",
        "报销要在多长时间内提交？",
        "紧急情况下应该联系谁？",
        "出差可以带家属吗？",
        "临时要延长出差时间怎么办",  # 语义题：关键词版容易检索偏，向量版应命中 FAQ
        "出差可以带宠物吗？",  # 负例：应诚实说「资料中没有提到」
    ]
    for q in tests:
        print("=" * 50)
        print(f"用户：{q}")
        print(knowledge_qa(q))
