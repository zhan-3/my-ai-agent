# 04 — fabrication 检测补政策锚（judge 无法抓「合理数字」的编造）

**Status:** needs-triage
**Blocked by:** 02（金丝雀集已落地，fab-01 红灯即本票要解决的问题）
**Type:** task

## 背景

金丝雀 canary-fab-01 实测被 judge 放过（5 PASS）：agent 编造「一线城市住宿标准 1800 元/晚、
五星级可全额报销无需审批」（真实 500），judge 理由「与提供的政策上下文完全一致，未编造任何数字」。

根因：`build_judge_input` 只喂 input/classify/agent/final，**没有喂政策 ground-truth**。
judge 评「忠实度」只能靠自身常识——抓得住「高铁 88 元」这种离谱数字（fab-02 已通过），
抓不住「1800 元」这种听起来合理但违反政策的数字。这是评测体系「回显过拟合」的深层病灶：
judge 闭卷考开卷题。

## 决策（二选一，或先 B 后 A）

### 选项 B（轻，推荐先做）：静态政策 ground-truth 表
- 在 judge prompt 附一张小额确定性政策表（抄 data/ 知识库的锚点数字）：
  住宿三档 500/400/300、餐补、交通报销规则等。
- 改动：judge.py 加常量表 + 塞进 `_JUDGE_SYSTEM`；重跑金丝雀确认 fab-01 转绿。
- 代价：只覆盖有明确数字锚点的；与 data/ 知识库会漂移，需有人维护同步。

### 选项 A（重，根治，后做）：注入 agent 实际检索到的 RAG 上下文
- trace 层记录 agent 检索到的 RAG 片段，`build_judge_input` 把它喂给 judge。
- judge 检测「输出 vs 它手头的证据」矛盾——这才是 RAG 系统里「编造」的正确定义。
- 代价：trace 结构改动 + build_judge_input 改动，中等改动，单独排期。

## 验收（若选 B）
- [ ] judge prompt 附政策锚表（住宿三档等确定性数字）
- [ ] `--judge-canaries` 全绿（14/14 → 15/15，fab-01 转 FAIL 且 good-02 政策正确对照仍 PASS）
- [ ] 门禁四步全绿

## 不做
- 自动维护政策表（拉 data/ 实时生成）——二期
