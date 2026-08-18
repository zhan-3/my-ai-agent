# ADR-0005：子 Agent 注册表驱动产品路径（多 Agent 化），撤销"插件机制旁路"决定

## 背景：一次理解修正

原要求原文："如果你的子 Agent 支持 动态发现机制，自动扫描注册、懒加载、渐进式披露，可加分。
例如：未使用的模块不加载；渐进式暴露，意图识别阶段仅加载元数据。"

初版 ADR-0005 将"子 Agent"误读为"应用的可选插件目录"，把动态发现/懒加载/渐进式披露
实现为旁路 `plugins/` 机制，并决定**产品路径不接插件路由**。事后对照确认：在多 Agent
（主管-工人）架构里，"子 Agent"即 worker 层本身——要求的是**主管能动态发现 worker、
worker 自动注册、未派发的 worker 不加载、意图识别阶段只加载 worker 元数据**。
原决定的三个旁路插件（policy/weather 影子复制、stats 孤儿意图）正是误读的症状。

**本 ADR 撤销初版决定**：产品路径改为注册表驱动（多 Agent 化），原要求逐条落到真实架构。

## 决定

- **子 Agent = 实体模块**：六个内置子 Agent 在 `src/xiao_wen/agents/`（itinerary/preference/
  history/knowledge/web/other + 外部扩展 `plugins/`），每个声明 `INTENT / DESCRIPTION / run(state) -> dict`。
- **注册表驱动主管**：Agent Loop 每轮从 `plugin_registry.discover()` 获取 manifest，生成模型可调用工具；
  调用时才通过 `load_agent()` 加载实现——新增子 Agent 时主管代码零改动。
- **优先级**：内置优先；外部扩展仅在意图不与内置冲突时并入（防撞车）。
- **外部扩展真实路由**：`plugins/stats.py`（差旅统计）成为真实第七意图，被意图识别发现并派发；
  原 policy/weather 与内置重名，删除（影子复制，无独立价值）。

## Considered Options

- **旁路机制（初版决定，撤销）**：机制存在于 plugins/ 目录、产品路径不接线。判定失败：
  "子 Agent 支持动态发现"的主体是 worker 层，旁路机制无法让主管动态认识 worker。
- **完整接线（选）**：worker 拆为子 Agent 实体，注册中心 manifest 直接成为主管 Loop 的工具清单。
  工具选择质量与 observation 回送由 Loop 接口测试和按需真实模型测试覆盖。

## Consequences

- 主管无需硬编码子 Agent：加一个模块到 agents/ 或 plugins/，下一轮即可重新发现并暴露为工具。
- manifest 只暴露意图和说明，工具执行前不加载子 Agent 实现。
- 未派发的子 Agent 不加载（懒加载：内置 import_module / 外部 exec_module，`_loaded` 缓存）。
- 分类 Schema 的意图字段从静态 Literal 六词改为 str + 运行时词汇表校验（动态化的固有代价，
  幻觉意图兜底归「其他」）。
