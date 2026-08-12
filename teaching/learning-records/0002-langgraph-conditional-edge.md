# 独立完成 LangGraph 条件路由图（五件套已掌握）

用户独立完成了第二课动手任务（homework/0002.py）：状态 + 节点 + 条件边的最小图，一次跑通。

## 用户做对的（证据：homework/0002.py 运行输出）
- 用**映射字典形式**的 add_conditional_edges + lambda 返回 state["route"]，路由正确
- 主动把 `route` key 加进 State（正是课程提示的坑）、用 `Literal["A","B"]` 标注合法值、比骨架多加了 identify 节点
- 北京/杭州两条分支均验证正确

## 需要养成的工程习惯（已当面提示）
1. **只测了一条路**（北京）——第二条杭州分支是老师代测的。以后自己两个分支都跑，「验证点」习惯对应作业演示要多个案例。
2. `message` 单数 key：不算错，但官方惯例是 `messages`（MessagesState / ToolNode 默认认这个名），接工具前统一。
3. `identified_city` 是 dead state——没人读的 key 不该留在 state 里。原则：state 只放会被读的 key。
4. 初始 `"route": ""` 不符 Literal 类型（TypedDict 不运行时校验所以没炸）——更干净：输入直接给合法值。

## Implications
- 五件套（State/Node/Edge/ToolNode/运行）已实际掌握，下一课可直接接真 LLM（ReAct 循环）
- 接 LLM 前需确认：用户用的 API 提供商与模型名（OpenAI/DeepSeek/豆包？）——已问过，未答
