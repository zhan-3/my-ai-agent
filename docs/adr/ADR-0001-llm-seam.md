# ADR-0001：模型接缝（LLM seam）设计

- 状态：已接受（2026-08）

`ChatOpenAI` 构造曾散落在图、RAG 和联网模块，重试/超时配置发生漂移，导入期构造还让单元测试与交付自检依赖凭据。决定：由 `src/xiao_wen/llm.py` 提供 `get_llm(*, override=None, **overrides)` 懒构造——首次调用时校验 3 个 `DEEPSEEK_*` 变量（缺失报齐）并组装默认配置，返回值包一层代理：`invoke` 走共享 `CircuitBreaker`（3 次失败 / 5 秒恢复期），其余方法透传；链（prompt+schema）留在各消费者模块懒构建。

## Considered Options

- **范围**：仅 LLM 接缝（选）—— vs 连同 embedding/HTTP 一并收编（否决：变更面大，HTTP 重试重复问题另行处理）。
- **熔断接线**：接缝处代理守卫（选，一处守卫全部调用点与链继承）—— vs 各调用点显式守卫（否决：易漏，正是要消除的漂移）。
- **校验范围**：仅 3 个 DEEPSEEK 变量（选）—— vs 含 DASHSCOPE 共 4 个（否决：接缝不该隐含对 embedding 路径的依赖）。

## Consequences

- rag.py / web.py 的 LLM 将获得它们原本没有的 `max_retries=2, timeout=30`（预期内的行为变化）。
- 导入核心模块不再需要凭据：单元测试与交付自检（无 .env 的干净临时目录）脱离环境变量。
- 熔断状态为进程级全局共享，符合当前单实例运行边界。
