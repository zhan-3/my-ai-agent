# LR-0008 · 向量检索升级（dashscope embedding + chromadb）

**日期**：2026-08-10（第七课后）
**主题**：把 RAG 检索层从关键词（BM25）升级为向量检索（阿里 text-embedding-v3 + chromadb）
**决策背景**：学生提问「embedding 真的不行吗」→ 逐项核查：pateway 中转站无 embedding 端点/无模型/文档不支持 → 顺藤摸瓜发现 DeepSeek 官方 API 也明确回复不支持 embedding → 学生决定引入阿里云 DashScope text-embedding-v3

## 关键决策与事实

1. **deepseek-v4-flash 是官方模型**（DeepSeek 官方新闻稿/API 文档/HF 仓库证实，旧名 deepseek-chat/reasoner 已停用），但 **DeepSeek 官方也不提供 embedding**（GitHub issue 官方回复 "We do not support these features at this moment"）——不是中转站的锅
2. **embedding 选型（业界主流）**：API 派 = OpenAI text-embedding-3 / 阿里 text-embedding-v3（中文综合最好之一，¥0.0007/千 token）；本地派 = BGE 系列（中文开源标杆）、Qwen3-Embedding。学生选阿里 v3（有免费额度、中文好）
3. **包管理规范化**：项目原本就是 uv 管理（pyproject.toml + uv.lock），但 langchain-openai/python-dotenv/jieba 是 pip 直装导致清单脱节 → `uv add dashscope langchain-openai python-dotenv jieba numpy chromadb` 统一，以后一律 uv add
4. **存储方案**：从 numpy(.npy) 文件缓存升级为 **chromadb**（嵌入式向量库，HNSW 近似最近邻 + 元数据 + 磁盘持久化）——学生主动追问「有没有用向量库」，说明对存储层有架构意识

## 实测结果（对比 0007 关键词版）

| 测试题 | 0007 BM25 | 0008 向量 |
|---|---|---|
| 住宿标准 | ✅ 一线500/二线400/三线300 | ✅ 完整 + 连锁酒店补充 |
| 报销时限 | ✅（靠查询改写） | ✅ 30自然日+逾期处理 |
| 紧急联系 | ✅ | ✅ 更全（110/120/119/122+客服+分机） |
| 带家属 | ✅ | ✅ |
| 延长出差时间（语义题） | ❌ 误命中环保文档 | ✅ 一次命中 FAQ 变更流程 |
| 带宠物（负例） | ✅ 诚实 | ✅ 诚实+区分家属条款 |

**结论**：向量版 6/6，无需查询改写；embedding 天然理解语义（「延长出差时间」vs「长时间不用电脑」）。索引 386 块持久化 chroma，复用秒级。

## 学生表现
- 主动质疑「真的不行吗」→ 值得肯定的验证意识（对工具能力矩阵的实证精神延续自 LR-0004）
- 主动问「有没有用向量库」→ 对存储架构有敏感性
- 用 uv 管理包 → 工程规范化意识

## 后续
- 第八课课程页：向量检索原理（embedding/余弦相似度/HNSW）+ 对比教学
- 作业文档素材：「先用关键词兜底、再升级向量」的完整演进过程 + 选型依据（阿里 v3 vs OpenAI vs BGE 的成本/中文/部署权衡）
