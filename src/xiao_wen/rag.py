"""RAG 模块：向量检索升级版知识问答（dashscope text-embedding-v3 + Chroma 余弦检索）
跑法：uv run python -m xiao_wen.rag
依赖：.env 里 DASHSCOPE_API_KEY（阿里云百炼）；numpy / chromadb（已装）

方案演进：早期用关键词检索（jieba 分词 + BM25）暴露语义天花板（「延长出差时间」误命中环保文档）后，换成向量检索；现行方案即向量版。

设计要点：
- 索引构建一次性：8 份文档分块 → 批量 embedding → Chroma 磁盘持久化
- 查询：问题 embedding → 余弦相似度 top-k（向量检索，无需查询改写）
- 生成：命中块拼进提示词 → LLM 依据资料回答
"""
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import SecretStr
import dashscope
from http import HTTPStatus
import chromadb

load_dotenv()

# 项目根目录 = src/xiao_wen/ 上溯三级（src → 项目根）
ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs" / "documents"
CHROMA_DIR = ROOT / "data" / "chroma"
EMB_MODEL = "text-embedding-v3"
EMB_DIM = 1024
BATCH = 10          # 每次 API 调用批量 embedding 条数
COLLECTION = "travel_docs"

# ---- 1. LLM（知识生成，配置同前）----
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)

# ---- 2. dashscope embedding ----
dashscope.api_key = os.environ["DASHSCOPE_API_KEY"]

def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量调用 text-embedding-v3，返回归一化向量列表"""
    vecs: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i : i + BATCH]
        resp = dashscope.TextEmbedding.call(
            model=EMB_MODEL, input=batch, dimension=EMB_DIM)
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(f"embedding 失败: {resp.code} {resp.message}")
        vecs.extend(e["embedding"] for e in resp.output["embeddings"])
        time.sleep(0.2)  # 限速，避免触发频率限制
    return vecs

# ---- 3. 分块（标题和内容同块）----
def load_chunks(max_len: int = 400):
    chunks = []
    for path in sorted(DOCS_DIR.glob("*.txt")):
        para: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                if para:
                    chunks.append((path.stem, " ".join(para)))
                    para = []
                continue
            para.append(line)
        if para:
            chunks.append((path.stem, " ".join(para)))
    final = []
    for stem, text in chunks:
        while len(text) > max_len:
            cut = text.rfind("。", 0, max_len)
            cut = cut if cut > 0 else max_len
            final.append((stem, text[: cut + 1]))
            text = text[cut + 1 :]
        if text:
            final.append((stem, text))
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
    return client.get_or_create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"})  # 余弦距离

def build_index(chunks):
    """文档块 → dashscope embedding → 存入 chroma（磁盘持久化）
    已存在（块数一致）则直接复用，不重复调 API"""
    col = get_collection()
    if col.count() >= len(chunks):
        print(f"（复用 chroma 持久化索引，{col.count()} 条）")
        return col
    print(f"（构建 chroma 索引：{len(chunks)} 块 × embedding，首次 1-2 分钟…）")
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
    return col

def search(query: str, col, k: int = 5):
    """问题 embedding → chroma 余弦检索 top-k（HNSW 近似最近邻）"""
    qv = embed_texts([query])[0]
    res = col.query(query_embeddings=[qv], n_results=k)
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        sim = 1 - dist          # 余弦距离 → 相似度
        out.append((sim, meta["source"], doc))
    return out

# ---- 5. 增强 + 生成 ----
knowledge_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是晓问公司的差旅政策顾问。严格依据【参考资料】回答用户问题。
规则：
- 只能依据资料中的内容回答；资料没有提到的，明确说「资料中没有提到」
- 回答用中文，简洁准确，可以直接引用原文数据（如金额、天数、标准）
- 不要编造政策"""),
    ("human", "【参考资料】\n{context}\n\n问题：{query}"),
])
knowledge_model = knowledge_prompt | llm

def knowledge_qa(query: str) -> str:
    chunks = merge_tiny_chunks(load_chunks())
    col = build_index(chunks)
    hits = search(query, col)
    if not hits:
        return "资料中没有找到相关内容。"
    context = "\n\n".join(
        f"--- 来源 {stem} ---\n{text}" for _, stem, text in hits
    )
    r = knowledge_model.invoke({"context": context, "query": query})
    return f"（向量检索 top-{len(hits)}，来源：{', '.join(s for _, s, _ in hits)}）\n\n{r.content}"

if __name__ == "__main__":
    tests = [
        "出差住宿标准是什么？",
        "报销要在多长时间内提交？",
        "紧急情况下应该联系谁？",
        "出差可以带家属吗？",
        "临时要延长出差时间怎么办",        # 语义题：关键词版容易检索偏，向量版应命中 FAQ
        "出差可以带宠物吗？",              # 负例：应诚实说「资料中没有提到」
    ]
    for q in tests:
        print("=" * 50)
        print(f"用户：{q}")
        print(knowledge_qa(q))
