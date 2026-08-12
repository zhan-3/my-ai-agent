# ADR-0002：会话循环收口，会话隔离暂缓

对话循环（读短期记忆 → 注入 → invoke → 写回两轮）此前在 webapp / system.__main__ / scheduler.__main__ / smoke 四处逐字重复。决定：新增 `session.py` 模块，暴露 `chat(text, session_id="default") -> ChatResult(answer, intent, reason)` 收口循环；异常向上抛，web 层保留兜底文案；`chat()` 的 graph 与 memory 可注入以便用假图测循环。**会话隔离明确暂缓**：`session_id` 参数保留但记忆仍是全局单文件（单用户演示语义），真实隔离待存储层改造时再做。

## Considered Options

- **归属**：新模块 session.py（选，system.py 保持纯图）—— vs 收进 system.py（否决：图与循环职责混在一个最重的模块里）。
- **隔离范围**：只收口循环（选）—— vs 顺带做按会话的记忆命名空间（否决：改了记忆存储接口与数据布局，范围显著变大）。
- **异常语义**：向上抛（选）—— vs 会话层吞异常返回兜底文案（否决：兜底是 web 层的既定职责，demo/smoke 需要看到真实异常）。

## Consequences

- system.py / scheduler.py 的 `__main__` demo 与 scripts/smoke.py 改为调用 `chat()`，循环样板消失。
- webapp 的 `session_id` 保持装饰性；修复其文档字符串中"内存 dict keyed by session_id"的失实描述。
