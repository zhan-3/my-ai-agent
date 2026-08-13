# 晓问（xiao_wen）项目交接文档

> 本文档供接手的 agent / 开发者快速接管项目。**开发前请先读**：`AGENTS.md`（门禁与规范）、`CONTEXT.md`（领域上下文）、`docs/adr/`（架构决策）、`docs/test-map.md`（测试地图）。

## 1. 一句话概览

**晓问**：企业差旅 AI 助手。对话式完成行程规划、差旅政策问答、出差偏好记忆、历史行程查询、实时信息（天气/汇率/空气质量）查询。中文界面，登录门控。

## 2. 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 · FastAPI · LangGraph · pydantic v2 · langchain-openai |
| LLM | DeepSeek（经 pateway 代理，`DEEPSEEK_*` 环境变量） |
| 前端 | React 19 · Vite · TypeScript · Tailwind v4 · shadcn 风格 · Vitest |
| 数据 | PostgreSQL（记忆持久化）；`data/` 内嵌知识库文档（政策/差旅标准） |
| 测试 | pytest（unit + integration 真 LLM）· ruff · mypy · Vitest |
| CI | GitHub Actions（见 §8） |

## 3. 运行与常用命令

```bash
# 一键全栈（后端 :8000 + 前端 :5173）
pnpm dev
# 端口被占时清理
pnpm dev:kill
# 后端测试门禁（顺序：fast first）
uv run ruff check src tests plugins
uv run pytest -m "not integration"
uv run mypy src/xiao_wen tests
# 前端测试
cd frontend && pnpm vitest run
# 意图黄金集回归（真实 LLM，烧 token，手动/CI 用）
uv run python scripts/golden_intents.py --threshold 0.95
# AI 用户模拟器（素材收集，见 §7）
uv run python /tmp/ai_user_sim.py --sessions 1 --turns 10 --seed 42
```

- `.env` 已配置 `DEEPSEEK_API_KEY/BASE_URL/MODEL`、`DASHSCOPE_API_KEY`（天气等联网查询）。**`.env` 含真实密钥，禁止提交**。
- 后端日志：终端输出；E2E 时可用 `tail -f /tmp/backend*.log`。

## 4. 架构（读代码顺序）

```
webapp.py        FastAPI 端点：/api/auth/*、/api/chat（POST + SSE）、/api/memory
session.py       chat()/stream_chat()：组装图、跑图、SSE 事件流、记忆写回
graph_builder.py LangGraph DAG：START → classify_intent → dispatch → p_* → merge → END（无回边）
intent.py        意图分类：6 内置意图 + 插件意图，few-shot + 边界规则 + 指代消解
agents/          子 Agent（行程规划/偏好/历史/知识/联网/其他），元数据 INTENT/DESCRIPTION
trip_planner.py  行程结构化（TripPlan pydantic 模型 + 日期解析 + 缺信息追问）
memory.py        偏好/历史记忆读写（PostgreSQL）
llm.py           唯一 LLM 接缝：懒构造 + 熔断器（ADR-0001）
stability.py     异常兜底文案
auth.py          JWT 认证（session_id = username）
```

关键设计（ADR 在 `docs/adr/`）：
- **分层测试**（ADR-0008）：unit 无 LLM；integration 真 LLM 仅 master push + secrets 门控。
- **LLM 单一接缝**（ADR-0001）：全系统模型构造只走 `llm.get_llm()`。
- **API 契约**（`frontend/src/api/contract.ts` 由 OpenAPI 生成，源头钉死）：
  - `POST /api/chat` → `{answer, intent, reason, plan: TripPlan|null}`
  - `GET/POST /api/chat/stream` → SSE：`start → intent → working(stage) → done(plan 为 dict) → error`
  - Bearer token；`session_id = username`。

## 5. 意图识别（第三阶段已完成）

- `src/xiao_wen/intent.py`：6 意图（行程规划/偏好记录/历史查询/知识问答/联网查询/其他）+ 插件意图动态目录。
  - 单 LLM 调用、json_mode 结构化输出（`intent/reason/subtasks`），temperature=0。
  - few-shot 示例 `_EXAMPLES` + 边界规则 `_BOUNDARY_RULES` + 指代消解（先识别查询对象再决定沿用上文）。
- 黄金集 `tests/data/intent_golden.jsonl`：**51 条**（行程13/历史9/知识9/偏好8/联网6/其他6），格式 `{input, recent?, expected, subtasks?, note}`。
- 回归脚本 `scripts/golden_intents.py`（独立脚本，非 pytest）：`--threshold` 通过率门禁，基线实测 4 次全 100%，CI 阈值 95%。
- **改 intent.py 的 prompt/schema 前后必跑黄金集**；真实误分类持续追加进黄金集。

## 6. 当前状态

已完成：栈搭建 → React 移植 → 行程规划 → SSE 流式 → OpenAPI 类型 → 主题打磨 → 一键启动 → 认证反馈 → 历史查询修复 → **两批真实 LLM E2E（12+18 场景）** → SSE plan 序列化/缺城市追问/空 answer 兜底修复 → **意图识别一二三阶段** → **黄金集 51 条 + CI 门禁**。

最近提交（本地，**尚未 push**）：
```
2a84a65 fix: mypy tests 全绿——补上 CI 级类型检查漏网（pre-existing 7 错）
f6d372b test: 黄金集扩至 51 条并接入 CI 门禁（第三阶段收尾）
9df2011 feat: 意图识别一二三阶段——few-shot 示例 + 边界规则 + 黄金测试集
87eac6d fix: SSE done.plan 序列化崩溃 + 缺城市追问 + 空 answer 兜底
```

## 7. AI 素材收集（本次会话产出）

用 **AI 用户模拟器**（`/tmp/ai_user_sim.py`，三层受控随机：人设卡随机组合 × 目标池抽取 × 表达概率分支）与真实后端对话收集素材，52 轮。产出已入库：

- `delivery/ai-material/material_reasonable.jsonl` — **21 条合理素材**（知识问答12/偏好3/历史3/联网2/其他1，含期望意图标注，可直接并入黄金集）
- `delivery/ai-material/material_bugs.jsonl` — **5 条漏洞**（详见 §9）

模拟器要点：seed 可复现；人设/目标/行为分支用随机数生成器确定性采样，"怎么说"交给 LLM（temperature 0.8）；记忆一致性靠把已说偏好注入下一轮 prompt。

## 8. CI（.github/workflows/ci.yml）

- `unit`：任何 push/PR 必跑（ruff + format + mypy **含 tests** + pytest 非 integration + PG）。
- `integration`：仅 master push + 仓库有 `DEEPSEEK_API_KEY` 才跑（fork PR 自动跳过防泄露）。
- `golden`：integration job 内一步，`uv run python scripts/golden_intents.py --threshold 0.95`。
- `docker`：镜像可构建。

**教训**：本地 mypy 必须跑 `uv run mypy src/xiao_wen tests`（不是只有 src），CI 与本地命令保持一致，否则历史债会漏网。

## 9. 待办（按优先级）

### 漏洞修复（素材收集发现，BUG-001 最严重）

| # | 严重度 | 类别 | 现象 | 复现输入 |
|---|---|---|---|---|
| BUG-001 | 🔴 高 | 历史查询空回复 | 无记录时**连续追问 7 次全返回空字符串**，无兜底文案无引导（`session.py` 空 answer 兜底对历史 agent 未生效？） | "帮我单独查一下杭州的出差记录，我记得那次住的是民宿" |
| BUG-002 | 🟡 中 | 偏好语义误录 | 「去过广州」「常去的城市」被记为**常驻城市**，污染记忆槽位（偏好提取提示词） | "我之前出差去过上海，住过全季酒店" |
| BUG-003 | 🟡 中 | 航班意图漂移 | 同类"查回程航班"被判 联网/历史/其他 三种，回复不统一（设计上行程相关动作→行程规划+追问，需统一） | "对了，顺便帮我查一下回程日期有没有航班" |
| BUG-004 | 🟡 中 | 知识检索不稳定 | 同一问题有时答"未提及"，有时答完整标准（知识库检索/提示词问题） | "公司差旅住宿和餐补标准是怎样的？" |
| BUG-005 | 🟢 低 | 偶发 LLM 错误 | 52 轮中 2 次"服务暂时不可用"（~4%），稳定性兜底生效但频率偏高 | 简单偏好陈述 |

### 可选后续（用户尚未决策）

1. **21 条合理素材并入黄金集**（51 → 72 条）后跑基线，确认无回退。
2. **轻量消歧**（路线图第四阶段修订版，曾否决多模型投票）：只对歧义子集反问，多轮实现（不加图回边）；不确定性信号先规则启发式。已调研：分层反问是成熟生产模式（Amazon Lex 同款），采样一致性 N=3-5 比自报置信度可靠。
3. 其他候选：行程 `from_city` 记为"无→北京"的一致性修复；更多 E2E 场景矩阵；SSE error 路径覆盖。

## 10. 操作陷阱（血泪教训）

- **pkill 和启动必须分两个 bash 调用**：`pkill -f "[x]iao_wen.webapp"`（方括号防自匹配）。
- E2E 后台进程跑完要清理，再让用户 `pnpm dev`。
- 改 intent.py 后跑黄金集看回退；CI 阈值是 95% 不是 100%（LLM 有真实方差）。
- `plan` 输出必须是 **dict**（`plan.model_dump()`），webapp 手写 json.dumps，TripPlan 实例会炸序列化。
- 单测 mock LLM 无法覆盖 webapp 手写 json.dumps 路径（scripted events 用 chunk 模拟），真实 astream_events 复刻才暴露。
- 缺城市/日期追问的「未知」集合统一为 `("待定","未知","出差")`。
