# ADR-0011：行程生命周期统一 trips 表

- 状态：已接受（2026-08）
- 相关：ADR-0006（Postgres 记忆）、ADR-0009（对话线程与活跃任务）、ADR-0003（行程规划）

## 背景

「行程」这一领域实体长期被劈成两张表：`itineraries`（已生成行程的要素 + 摘要）与
`active_tasks`（线程内未完成任务的缺项 + 续接文本）。由此产生四类问题：

1. **状态散落**：行程是「规划中」还是「已完成」靠猜——`active_tasks` 表有没有、`start_date`
   是不是未来，没有显式状态字段。
2. **无稳定身份**：`itineraries` 去重靠 `(出发日, 出发地, 目的地, 天数)`，改期即失配 → 新增而非
   更新，用户「改个日期」会得到两条档案；前端「继续对话/改期/取消」无处引用目标行程。
3. **丢失完整 plan**：落库只存 `plan.summary`，`ItineraryPlan.days`（每天交通/住宿/活动）被丢弃，
   前端展开详情永远只能看一段摘要。
4. **单任务主键**：`active_tasks.thread_id` 是主键，一个线程只能有一个活跃任务，一轮对话规划
   两条行程时续接上下文互相覆盖。

## 决策

1. **统一 `trips` 表**，稳定 `id`（BIGSERIAL）贯穿行程全生命周期；废除 `itineraries` 与
   `active_tasks` 两张表。

   ```
   trips: id, user_id, thread_id, status, facts(JSONB), plan(JSONB),
          missing(JSONB), resume_context(TEXT), created_at, updated_at
   ```

   - `user_id` = 长期记忆所有者（跨线程）；`thread_id` = drafting 态所在线程（续接用）。
   - `facts` = 差旅要素（城市/日期/天数/人数/返程/预算/校验状态）。
   - `plan` = 完整行程 `days + summary + reasons`（drafting 时为 NULL）。

2. **四态状态机**：`drafting（规划中）/ upcoming（待出发）/ completed（已完成）/ cancelled（已取消）`。
   - `drafting`：要素不全、正在追问缺项（`missing` 非空）。
   - `upcoming`：要素齐全、已生成、未结束；可改期/取消。
   - `completed`：行程已结束（读时按日期派生：`today > 返程日/最后一天`），另允许手动标记；
     只读，附报销时限提醒。
   - `cancelled`：用户取消；终态，保留记录不物理删除。
   - 「进行中（出差期间）」**不设独立存储状态**——它是 `upcoming` 在展示时按日期派生的标签
     （出发日 ≤ today ≤ 最后一天），不占状态、不挂操作（期间无改期/取消意义）。

3. **完成边界 = 返程日/最后一天已过**（`today > 最后一天`），读时自动判定，复用
   `stats.classify` 的确定性日期规则，不写后台 job。

4. **报销只提醒不追踪**：`completed` 态展示「出差结束后 N 日内提交报销」（N 读自 RAG
   `reimbursement_deadline` fact）；不存 `reimbursed` 标记——报销是财务域执行动作，晓问是前台
   智能，只提醒时机不替财务记账。

5. **完整 plan 落库**：`trips.plan` 存 `days + summary + reasons`，前端展开详情可展示每天行程。

6. **drafting 集合式续接**：主管每轮注入「该线程**所有** `drafting` 行」的摘要 + 缺项，由 LLM
   判断用户续接哪条；不再设「单活跃任务」指针。`get_active_task`/`set_active_task`/
   `clear_active_task` 降级为 trips 表 drafting 行的兼容适配（对外形状不变：`intent/
   resume_context/missing`，附加 `trip_id`）。
   **生成成功不发 `clear`**：`drafting → upcoming` 由 `save_trip(trip_id)` 在同一事务内更新同一
   行完成；若先 `clear` 再写会把绑定 `trip_id` 的草稿删掉，使更新落空。`clear`/`cancel` 仅保留给
   兼容接口与「用户取消」语义（`task_update_cancel` → `cancel_active_task` 转 `cancelled`，
   保留记录不物理删除）。

7. **改期 vs 再来一次分开**：改期/改天数/改城市 = 更新同一 `trip_id`（`update_trip`）；「参考此
   行程再来一次」= 复制 `facts` 开新 `trip_id`（`duplicate_trip`）。取消 = `cancel_trip`。
   前端两个按钮，语义各归各位。

8. **迁移**：开发库数据量极小（2 条测试行程），drop 旧表建 `trips`，不写迁移脚本。

## 后果

- 前端记忆侧栏改三分区：规划中 / 待出发 / 已完成（含已取消），每项带稳定 `id` 供操作。
- `agent_loop` 中 `_trip_requested` 门禁与 active-task 读取继续工作：`get_active_task` 兼容返回
  最近一条 drafting 的形状，`_trip_requested` 只需知道「有活跃行程且缺什么」，不感知表结构。
- 旧数据（`itineraries` + `active_tasks`）不复用，清空重建；历史查询/差旅画像改读 `trips`。
- 表结构属「难逆转」变更，故立此 ADR 记录；「统一 vs 渐进加字段」的权衡见背景。
