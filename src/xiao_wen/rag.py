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
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus

import chromadb
import dashscope
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate

from xiao_wen import ROOT, llm
from xiao_wen.stability import with_retry

load_dotenv()

# 项目根目录（单一来源：xiao_wen.ROOT，C7 收敛）
DOCS_DIR = ROOT / "docs" / "documents"
CHROMA_DIR = ROOT / "data" / "chroma"
# embedding 模型可配置（.env 覆盖；换模型必须重建索引，见 build_index 模型版本检查）
EMB_MODEL = os.environ.get("DASHSCOPE_EMB_MODEL", "text-embedding-v3")
EMB_DIM = int(os.environ.get("DASHSCOPE_EMB_DIM", "1024"))
BATCH = 10  # 每次 API 调用批量 embedding 条数
COLLECTION = "travel_docs"

# 检索相似度阈值：低于此值的命中视为语义无关丢弃（防无关文档拼进提示词引发幻觉）。
# text-embedding-v3 余弦相似度：相关文档通常 >0.4，无关 <0.3；可 .env 用 RAG_MIN_SIM 覆盖。
MIN_SIM = float(os.environ.get("RAG_MIN_SIM", "0.35"))


@dataclass(frozen=True)
class Evidence:
    """一条可追溯的检索证据；ID 对同一来源和文本稳定。"""

    evidence_id: str
    source: str
    text: str
    similarity: float
    section: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class PolicyFact:
    """由可见政策原文确定性抽取的事实；每个事实必须绑定证据。"""

    key: str
    value: int | float | str
    unit: str
    scope: dict[str, str]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PolicyContext:
    """本轮政策检索快照，供行程生成和运行时验证共同使用。"""

    query: str
    evidence: tuple[Evidence, ...]
    status: str = "not_found"  # grounded / partial / not_found
    facts: tuple[PolicyFact, ...] = ()
    snapshot_id: str = ""

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)

    @property
    def text(self) -> str:
        return "\\n\\n".join(item.text for item in self.evidence)


def _extract_policy_facts(evidence: tuple[Evidence, ...]) -> tuple[PolicyFact, ...]:
    """从已检索原文提取当前 Demo 所需的有限政策事实，不从模型输出提取。"""
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
        ]
        for key, pattern, unit, scope in patterns:
            match = re.search(pattern, text)
            if match:
                facts.append(PolicyFact(key, int(match.group(1)), unit, scope, evidence_ids))
    # 同一事实出现冲突时不选择其中一个；调用方可据此要求确认。
    unique: dict[tuple[str, str], PolicyFact] = {}
    for fact in facts:
        identity = (fact.key, repr(sorted(fact.scope.items())))
        prior = unique.get(identity)
        if prior is None or prior.value == fact.value:
            unique[identity] = fact
        else:
            unique.pop(identity)
    return tuple(unique.values())


def policy_context_from_texts(query: str, texts: list[tuple[str, str]]) -> PolicyContext:
    evidence = tuple(Evidence(_evidence_id(source, text), source, text, 0.0) for source, text in texts)
    facts = _extract_policy_facts(evidence)
    snapshot = hashlib.sha256("\\n".join(item.evidence_id for item in evidence).encode()).hexdigest()[:16]
    return PolicyContext(
        query=query,
        evidence=evidence,
        facts=facts,
        status="grounded" if evidence else "not_found",
        snapshot_id=f"policy-{snapshot}",
    )


# ---- 1. LLM（知识生成，走单一接缝，懒构建）----
# ---- 2. dashscope embedding（懒校验 + 重试：导入不读 env，首次调用才校验）----
_EMBED_ENV_VAR = "DASHSCOPE_API_KEY"


def _validate_dashscope() -> None:
    key = os.environ.get(_EMBED_ENV_VAR)
    if not key:
        raise RuntimeError(f"缺少 embedding 必需环境变量：{_EMBED_ENV_VAR}（请在 .env 中配置）")
    dashscope.api_key = key


@with_retry(retries=2, base_delay=0.5)
def _embed_batch(batch: list[str]):
    """单批 embedding（指数退避重试，容忍免费 API 抖动）"""
    resp = dashscope.TextEmbedding.call(model=EMB_MODEL, input=batch, dimension=EMB_DIM)
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

    索引版本化（防 stale）：块数一致**且** collection 元数据记录的模型名与当前一致才复用；
    换 embedding 模型（如 v3→v4）后旧向量与新区块不在同一向量空间，即使维度相同也必须
    清空重建——块数一致复用的旧逻辑防不了换模型，这里补上模型版本检查。
    """
    col = get_collection()
    meta = getattr(col, "metadata", None) or {}
    existing = col.count()
    if existing == len(chunks) and meta.get("model") == EMB_MODEL:
        print(f"（复用 chroma 持久化索引，{existing} 条 · {EMB_MODEL}）")
        return col
    if existing:
        print(f"（索引过期：现有 {existing} 条 / 模型 {meta.get('model')} ≠ {EMB_MODEL}，清空重建…）")
        col.delete(ids=col.get()["ids"])
    print(f"（构建 chroma 索引：{len(chunks)} 块 × {EMB_MODEL}，首次 1-2 分钟…）")
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        vecs = embed_texts([t for _, t in batch])
        col.upsert(
            ids=[f"c{i + j}" for j in range(len(batch))],
            embeddings=vecs,
            documents=[t for _, t in batch],
            metadatas=[{"source": stem} for stem, _ in batch],  # 元数据：可按来源过滤
        )
        time.sleep(0.2)
    col.modify(metadata={"model": EMB_MODEL})  # 记录模型版本（不能带 hnsw:space，chromadb 拒绝改距离函数）
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


def search(query: str, col, k: int = 5, min_sim: float | None = None):
    """问题 embedding → chroma 余弦检索 top-k（HNSW 近似最近邻）

    复合问句（含和/与/以及/、）拆成子问句多路检索后合并去重：
    每个子主题的命中块都进入候选，按相似度降序取 top-k。
    复合问句按主题均分席位（每子问句取 ceil(k/份数)），避免单一主题霸榜。
    min_sim：相似度阈值，低于此值的命中丢弃（默认 MIN_SIM，可显式传入用于测试）。
    """
    threshold = MIN_SIM if min_sim is None else min_sim
    subs = _split_compound_query(query)
    per = max(1, -(-k // len(subs)))  # 每子问句席位：k 按主题数均分向上取整
    out: dict[str, tuple[float, str, str]] = {}
    for sub in subs:
        qv = embed_texts([sub])[0]
        res = col.query(query_embeddings=[qv], n_results=per)
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True):
            sim = 1 - dist  # 余弦距离 → 相似度
            out.setdefault(doc, (sim, meta["source"], doc))
    ranked = sorted(out.values(), key=lambda t: t[0], reverse=True)
    return [t for t in ranked if t[0] >= threshold][:k]


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


def retrieve_policy(query: str, k: int = 5) -> PolicyContext:
    """检索并保留证据身份；异常或无命中明确返回 not_found。

    目前复用 search_texts 这个既有检索接缝，确保测试适配器和旧调用仍能注入
    检索结果；后续 PolicyFact 阶段再把相似度/章节元数据完整接入这里。
    """
    try:
        texts = search_texts(query, k=k)
        hits = [(0.0, "legacy-search_texts", text) for text in texts]
    except Exception:
        hits = []
    context = policy_context_from_texts(query, [(source, text) for _, source, text in hits])
    return PolicyContext(
        query=context.query,
        evidence=tuple(
            Evidence(item.evidence_id, item.source, item.text, hit[0])
            for item, hit in zip(context.evidence, hits, strict=True)
        ),
        facts=_extract_policy_facts(context.evidence),
        status=context.status,
        snapshot_id=context.snapshot_id,
    )


def search_texts(query: str, k: int = 5) -> list[str]:
    """纯检索（无 LLM）：返回命中文本段列表（空 = 无命中/索引不可用）。

    供 collect-then-compose 收集者（行程规划等）注入上游上下文：
    只要政策原文，不需要知识问答 agent 的一轮 LLM 生成。索引/网络异常降级空列表，不阻塞。
    """
    try:
        chunks = merge_tiny_chunks(load_chunks())
        col = build_index(chunks)
        hits = search(query, col, k=k)
        return [text for _, _, text in hits]
    except Exception:
        return []


def knowledge_qa(query: str) -> str:
    """RAG 知识问答：检索 top-5 → 组装上下文 → LLM 生成
    检索来源写入日志（可追溯），答案不携带技术细节（前端保持干净）"""
    chunks = merge_tiny_chunks(load_chunks())
    col = build_index(chunks)
    hits = search(query, col)
    if not hits:
        return "资料中没有找到相关内容。"
    from xiao_wen.stability import logger

    logger.info("RAG 检索 top-%d 来源：%s（问题：%s）", len(hits), [s for _, s, _ in hits], query)
    context = "\n\n".join(f"--- 来源 {stem} ---\n{text}" for _, stem, text in hits)
    r = _knowledge_model().invoke({"context": context, "query": query})
    return r.content


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
