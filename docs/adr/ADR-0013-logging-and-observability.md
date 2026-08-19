# ADR-0013：日志体系（stability.log 双写 + 模块命名 + 噪音静音）

- 状态：已接受（2026-08）
- 相关：ADR-0001（LLM seam）、ADR-0008（CI 部署）、AGENTS.md `### Logging`

## 背景

项目曾依赖两套并存手段观察运行行为：早期 `observability.py` 的 JSONL 逐轮 trace
（调试期旁路，含完整用户对话），以及散布的 `print`/裸 `except: pass`。实机排障时发现：

1. `observability` trace 复制了已持久化在 Postgres 的对话与工具轨迹，且多落一份
   「含用户对话的 JSONL」文件，是调试残留而非系统性观测（已整体删除，见后续决策 4）。
2. 库级日志默认全量输出：`httpx` 每次 HTTP 请求的 INFO 曾占 `stability.log` 93.8%
   的行数，业务日志被淹没。
3. 静默降级点（天气/空气/汇率失败、`except: pass`）没有日志，失败原因不可追溯。

## 决策

1. **双写目的地**：`logging.basicConfig` 全局配置（stdout + `data/stability.log`），
   由 `stability.py` 单点建立；`data/stability.log` 按天滚动（`TimedRotatingFileHandler`
   `when="midnight"`，保留 7 天），git 忽略。
2. **模块命名**：业务日志用 `logging.getLogger("xiao_wen.<module>")`；INFO 记关键路径，
   WARNING/ERROR 记失败与静默降级，必须带原因，禁止裸 `except: pass`。
3. **噪音静音**：`httpx` logger 压到 WARNING（成功请求无需记录，失败路径已有自有
   WARNING 埋点）；不重新打开。
4. **删除 observability**：JSONL 逐轮 trace、config 两字段、webapp 包装、
   session `recorder` 参数、`OBSERVABILITY_*` 环境变量全部移除——对话与工具轨迹本就
   持久化在 Postgres（`messages` / `agent_transcripts`），事后复盘直接查库，
   系统性日志负责运行期错误。

## 后果

- 排障顺序：`data/stability.log` 看运行期错误 → 查库复盘对话/轨迹 → 对话回归集兜底。
- 不引入新依赖：复用 stdlib `logging`；`stability.py` 是唯一配置点。
- 已知边界：stdout 只在前台运行可见（nohup/容器各有自己的 stdout 去向）；JSONL trace
  不再存在，需要逐轮完整事件流时用数据库记录。
