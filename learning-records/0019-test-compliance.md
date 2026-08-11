# LR-0019 · 测试符合性核对 + tests/ 类型检查清零

**日期**：2026-08-11
**主题**：用户问「这个测试符合标准吗？用 mypy 纠正 test/ 类型错误」

## 核对结论（对照作业加分项 E 原文）

作业 E 要求三件事，逐条核对：

| 作业要求 | 现状 | 结论 |
|---|---|---|
| 设计典型测试用例 | 参数化用例表（意图 7 例含边界、记忆 5 例…） | ✅ |
| 对**意图识别、记忆、RAG、规划**效果进行验证 | 意图 ✓ 记忆 ✓ 规划 ✓ **RAG ✗（缺失）** | ⚠️ 补 test_rag.py |
| 提供自动化/回归测试 | 分层 pytest（单元 + `-m integration`） | ✅ |

→ **结论：整体符合，但 RAG 是作业点名的验证对象，此前没有专门测试——补齐后才完全符合。**

## 补 test_rag.py（6 个用例，双版本对照）

- 单元层（0007 BM25，**纯本地零 API**）：8 文档全覆盖 / 块长 ≤400 / 短块合并 / 中文分词 / **BM25 检索「住宿标准」命中 01_travel_standards 且分数降序**
- 集成层（0008 向量，`-m integration`）：真实 embedding 检索 top-1 命中差旅标准文档、相似度降序、文档含关键词

## mypy 修 tests/（14 错误 → 0）

两类错误：
1. **import-not-found**（memory_store/plugin_registry/stability）：tests 运行时靠 conftest 把 homework/ 加进 sys.path，mypy 不知道 → 配置声明 `mypy_path=["homework"]`（与运行时一致，非掩盖）
2. **union-attr/arg-type**（importlib `_spec` 可能 None）：0010 的 `_load` 有收窄，tests 里三个文件复制时丢了 → 补 `if spec is None or spec.loader is None: raise ImportError`（真代码修法，与 homework 同款）

顺带：`files = ["homework", "tests"]` 把 tests 纳入 mypy 范围。

## 结果

- **测试 41 个全绿**：单元 32（含 RAG 5）+ 集成 9（含向量 RAG 1，分层语义修正：新向量测试最初漏打 `@pytest.mark.integration` 被当单元跑，修正后归位）
- **mypy 24 文件 0 错误**（homework 16 + tests 8）

## 学生表现
- 主动拿作业原文当尺子自查测试（核对意识），并发现类型检查没覆盖 tests

## 下一步
- 提交；最终收尾（录屏 + 打包 + 提交邮件）不变
