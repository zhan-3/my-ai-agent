# 06 — SSE error 路径覆盖

**What to build:** 补 SSE 错误路径测试覆盖。既有防御设计是两层：
stream_chat try/except（熔断降级）+ 端点 gen() 防御包装（客户端永不悬挂）。
本次只补覆盖，验证设计有效（预期零源码改动）。

| 路径 | 现状 | 测试 |
|---|---|---|
| 启动即炸 | ✅ 已有 | test_stream_chat_error_yields_error_event |
| 流中途炸（已发部分事件） | 代码有，无测试 | ➕ 本次 |
| 图空产出（final=None 防御分支） | 代码有，无测试 | ➕ 本次 |
| 端点层未消化异常 → error 帧 | 代码有，无测试 | ➕ 本次 |

**Blocked by:** None

**Status:** resolved

- [x] session 层：中途炸 → error 收尾、无 done、不写回记忆；空产出 → error 非假 done
- [x] webapp 层：stream_chat 未消化异常 → 端点仍产 error SSE 帧
- [x] 门禁全绿

## Answer

已实现并验证：+3 测试（session 层 2 + webapp 层 1），防御设计验证有效，
零源码改动。门禁全绿（ruff/pytest 170/mypy）。
