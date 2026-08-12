# ADR-0003：行程规划管线抽为 trip_planner.py，行为保持

行程 worker 的六步编排（提取 → 常驻城市补全 → 缺项检查 → 生成 → 写回 → 格式化）此前是 system.py 节点内的内联逻辑，只有两个纯函数可测。决定：抽为新模块 `trip_planner.py`，单一接口 `plan(facts, prefs) -> ItineraryPlan | NeedsInfo`（判别式返回），记忆读写收进实现；graph 节点缩为一行调用。**编排顺序是产品行为，保持不变**：常驻城市补全先于缺项检查（"用户没说出发城市但记忆里有"不算缺项），缺项短路不调生成，写回发生在生成成功后。

## Considered Options

- **返回形态**：判别式 `ItineraryPlan | NeedsInfo`（选，缺项清单可被测试断言）—— vs 直接返回最终文案字符串（否决：缺项语义埋进字符串，测试只能搜关键词）。
- **行为**：保持现状（选）—— vs 趁机改顺序/语义（否决：补全先于检查是已验收的产品行为，加深不等于改行为）。

## Consequences

- 编排逻辑首次获得测试面；scheduler 并行路径（fan-out/fan-in）测试一并补齐（C3 Q4 记录的空白）。
