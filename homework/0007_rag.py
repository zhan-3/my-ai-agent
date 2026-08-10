"""第七课：知识问答（RAG）—— 用企业差旅文档回答政策问题
跑法：python homework/0007_rag.py
依赖：项目根目录 .env；jieba（已装）

RAG = 检索(Retrieve) + 增强(Augment) + 生成(Generate)：
  ① 索引构建（一次性）：8 份文档 → 分块 → 每个块建词频索引
  ② 检索：问题分词 → 对索引打分 → 取相关 top-k 块
  ③ 增强：把命中的块拼进提示词
  ④ 生成：LLM 只依据给定资料回答，资料没有就明说

注意：中转站不支持 embedding（404），所以检索用关键词（TF）方案。
真实产品会用向量检索；但「索引与查询分离」的思路完全一致。
"""
import os
import math
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import SecretStr
import jieba  # type: ignore[import-untyped]

load_dotenv()

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "documents"

# ---- 1. LLM（同一套可用配置；知识问答输出文本，不需要 json_mode） ----
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)

# ---- 2. 索引构建（一次性）----
def load_chunks(max_len: int = 400):
    """读全部文档 → 按空行分段 → 超长段折半 → 每个块带来源文件名"""
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
    # 超长块折半（保持每块不至于撑爆上下文）
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
    """短块（<min_len 字，多为纯标题）与下一块合并，标题和内容进同一块
    否则 BM25 块长归一化会优待短标题块，检索到标题却拿不到内容"""
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


STOPWORDS = set("""的了在是 要 就 都 也 还 很 不 没 别 这 那 和 与 或 又 及 而 之 其 该 怎 应该 什么 谁 多长 如何 哪个 哪些 请问 我 需要 想 了解 告诉 一下 帮忙 可以 能 会 愿 请 吧 吗 呢 啊 一个 有 是否 怎么 怎样 多久 多长时间 相关 关于""".split())


def tokenize(text: str) -> list[str]:
    """精确分词 + 全模式只补 2 字词（"多长时间"能补出"时间"），过滤单字与停用词
    停用词不参与打分：否则 "长时间不用电脑" 的环保文档会误伤差旅查询"""
    words = set()
    for w in jieba.lcut(text):
        if len(w) > 1 and w not in STOPWORDS:
            words.add(w)
    for w in jieba.lcut(text, cut_all=True):
        if len(w) == 2 and w not in STOPWORDS:
            words.add(w)
    return list(words)


def build_bm25(chunks):
    """BM25 索引：每块词频表 + 全局文档频率 df"""
    tf_list: list[dict[str, int]] = []
    df: dict[str, int] = {}
    N = len(chunks)
    for _, text in chunks:
        tf: dict[str, int] = {}
        for w in tokenize(text):
            tf[w] = tf.get(w, 0) + 1
        tf_list.append(tf)
        for w in tf:
            df[w] = df.get(w, 0) + 1
    return tf_list, df, N


def bm25(query: str, chunks, tf_list, df, N, k: int = 5, per_source: int = 3, k1: float = 1.5, b: float = 0.75):
    """BM25 打分：
    - 词频归一化：短块不吃亏
    - IDF：惩罚到处都有的词（如"报销"），突出独特词（如"时限"）
    - 块长归一化：长块不占便宜
    - 来源去重：同一文档最多取 per_source 块，避免一个源霸占全部名额
    """
    q_words = tokenize(query)
    avg_len = sum(sum(tf.values()) for tf in tf_list) / N
    scored = []
    for i, tf in enumerate(tf_list):
        doc_len = sum(tf.values())
        score = 0.0
        for w in q_words:
            f = tf.get(w, 0)
            if f == 0:
                continue
            idf = math.log((N - df.get(w, 0) + 0.5) / (df.get(w, 0) + 0.5) + 1)
            score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * doc_len / avg_len))
        if score > 0:
            scored.append((score, i))
    scored.sort(reverse=True)
    # 来源去重后取 top-k
    out: list[tuple[float, str, str]] = []
    seen_src: dict[str, int] = {}
    for s, i in scored:
        stem = chunks[i][0]
        if seen_src.get(stem, 0) >= per_source:
            continue
        seen_src[stem] = seen_src.get(stem, 0) + 1
        out.append((s, stem, chunks[i][1]))
        if len(out) >= k:
            break
    return out

# ---- 3. 查询改写 + 检索 + 生成 ----
# 用户问「多长时间内提交」→ 文档写「30 个自然日内 / 时限」：问法与文档用词对不上，
# 关键词检索会漏。用 LLM 把问句改写成检索关键词（Query Rewriting，业界标准手法）。
rewrite_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是检索查询改写器。把用户的问题改写成 3-5 个核心检索关键词（空格分隔），
用于在『企业差旅政策文档库』里做关键词搜索。要求：
- 聚焦具体名词（城市级别、金额、酒店、每晚、时限、联系人等），包含同义词
- 不要泛词（报销、政策、规定、费用这类太泛的词不要）
只输出关键词本身，不要其他内容。"""),
    ("human", "{query}"),
])
rewrite_model = rewrite_prompt | llm

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
    resp = rewrite_model.invoke({"query": query})
    text = resp.content
    assert isinstance(text, str)  # 纯文本模型输出 content 为 str
    q_rewritten = text.strip()  # ① 查询改写
    chunks = merge_tiny_chunks(load_chunks())   # 每次运行重建索引（演示用；真实产品常驻内存/数据库）
    tf_list, df, N = build_bm25(chunks)
    hits = bm25(q_rewritten, chunks, tf_list, df, N)
    if not hits:
        return "资料中没有找到相关内容。"
    context = "\n\n".join(
        f"--- 来源 {stem} ---\n{text}" for _, stem, text in hits
    )
    r = knowledge_model.invoke({"context": context, "query": query})
    return f"（检索词：{q_rewritten}；命中 {len(hits)} 段，来源：{', '.join(s for _, s, _ in hits)}）\n\n{r.content}"

if __name__ == "__main__":
    tests = [
        "出差住宿标准是什么？",
        "报销要在多长时间内提交？",
        "紧急情况下应该联系谁？",
        "出差可以带家属吗？",          # 文档大概率没有 → 应明说
    ]
    for q in tests:
        print("=" * 50)
        print(f"用户：{q}")
        print(knowledge_qa(q))
