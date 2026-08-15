# held-out 集使用规则

`holdout_golden.jsonl` 是意图分类的**防过拟合对抗集**：样本从未参与 `intent.py`
的规则/词表/few-shot 调参，存在的意义就是「没被看过」。

1. 本集样本【禁止】用于调 `intent.py` 的规则/词表/few-shot。
2. 修改 `intent.py` 分类相关代码的提交，必须跑 `--set holdout` 并在提交信息附分数。
3. holdout 失败样本要修复时：把该样本【移入】`intent_golden.jsonl`（此后它算训练集），
   再补一条同类新样本进 holdout——集合大小不减。
4. holdout 分数低于 0.9：不是改样本，是停下来看规则层是否过拟合。

跑法：`uv run python scripts/eval/run.py --set holdout`（阈值默认 0.9，需 .env 密钥）。
