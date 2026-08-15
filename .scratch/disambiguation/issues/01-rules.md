# 01 — 消歧规则模块

**What to build:** 纯规则函数 `disambiguation.clarify(user_input, intent_name)`：命中歧义子集（航班信息类 / 咨询建议类）返回带 ①② 选项的反问问题文本，否则返回 None。不调用 LLM，可单测。

**Blocked by:** None — can start immediately

**Status:** resolved

- [ ] `src/xiao_wen/disambiguation.py`：触发器 A/B，意图+模式双重匹配，订/买与休闲类不触发
- [ ] `tests/test_disambiguation.py`：正例（查航班/有没有航班/住哪里比较好/推荐）+ 反例（订机票/规划行程/杭州有什么好玩的/政策标准查询）
- [ ] ruff + pytest -m "not integration" 通过

## Answer

已实现并验证（见提交消息），单测/集成/黄金集全绿。

## Answer

已实现并验证：规则模块 + 12 单测全绿（触发器 A/B/C、订买与休闲反例）。
