# judge 硬化：区分度证明 + 一票否决 + 分维度分数

Status: ready-for-agent
Type: spec
Feature: judge-hardening

> 一句话：judge 层（layer 3）当前 20/20 全 PASS、均分 4.95——它还没证明过自己能
> 抓住坏回答。本 spec 用三张票把它从「昂贵的橡皮图章」变成「可信的质量门」。

## Problem Statement

1. **区分度未证明**：锚点修正后（human_review.md），评测样本几乎全是「缺要素→索取」
   场景，按新锚点必然满分。judge 从未在已知坏回答上验证过——它可能对任何回答都打 5 分。
2. **平均分聚合有洞**：总分 = 五条 rubric 平均取整，verdict = score>=4。忠实度 1 分
   （编造事实）可被其他四条 5 分平均成 4 → PASS。这与 rubric 自己写的「编造明显事实
   ≤2 分」相矛盾——扣分被平均洗掉了。
3. **分维度分数丢失**：`JudgeOutput` 只有总分 + reasons 字符串，无法统计「哪条 rubric
   最常失分」，报告只能看总分曲线。
4. **temperature=0 下 N=3 多数票纯烧钱**：三次调用结果几乎恒同（judge.py docstring
   自己承认「方差来自模型自身漂移」），2/3 的 token 不产生信息。
5. **考官=考生在实际运行**：judge_report.md 显示 `DEEPSEEK_*（回退）`。设计有独立
   env 但没配，同源偏差只被「标注」没被「阻断」。

## Solution

- 票 #01：`JudgeOutput` 改为分维度分数（criteria dict），总分与 verdict 由**代码**计算；
  忠实度/合规性 ≤2 一票否决（FAIL），不参与平均洗白。
- 票 #02：金丝雀突变集——手工构造 10 条已知坏回答的 trace 事件，judge 必须打低分；
  这是 judge 层自身的回归门禁（judge 的验收 = 能把坏的打低，不是把好的打高）。
- 票 #03：默认 N=1（省 2/3 token）；回退同模型时显著告警 + 可选硬阻断开关。

## 执行顺序

#01 → #02（金丝雀断言依赖 #01 的 criteria/veto 语义）→ #03（独立，可并行于 #02）。

## 不做（后续/待议）

- 跨模型投票（多数票的正确形态）——等配了第二个 judge 模型再说
- judge 扩面到知识问答集（RAG 忠实度）——等 D5 七集落地
- 能力外样本是否保留在 judge 评测集（human_review.md 遗留问题）
