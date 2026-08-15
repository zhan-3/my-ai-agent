# 01 — `_split_subtasks` 兜底的递归护栏 + 触发率可见

**Status:** resolved
**Blocked by:** None
**Type:** task
**Feature:** split-guard

## 背景

`src/xiao_wen/intent.py` 的 `classify()` 末段有拆分兜底：LLM 未给 subtasks 且输入含
强拆分标记时，`_split_subtasks` 确定性切句，**每个子句再递归调 `classify()`**。问题：

1. 子句的递归 classify 内部又会走同一段兜底——子句里若还有「标记+前置分隔符」
   会继续拆、继续递归（文本每层变短所以不会死循环，但深度和 LLM 调用次数不可控）；
2. 子句还会穿过 `_recover_pending` / `_pref_only_correction` 两个规则修正，
   片段文本触发这些整句规则的行为没人推演过；
3. 这个兜底每触发一次 = 至少一次额外 LLM 调用（延迟+成本翻倍），但**没有任何
   日志/计数**，无法评估它的实际触发率和收益。

## What to build

### 1. 递归护栏

`classify()` 加内部参数（keyword-only，默认值保持外部签名兼容）：

```python
def classify(recent: str, user_input: str, *, _depth: int = 0) -> IntentResult:
```

- 拆分兜底段仅在 `_depth == 0` 时执行（子句分类调用 `classify(recent, chunk, _depth=1)`）
  → 子句不再二次拆分，递归深度封顶 1
- 子句分类结果只取 intent（现状如此），行为不变；docstring 注明护栏语义

### 2. 触发率可见

- 模块级引入 `logging.getLogger(__name__)`（项目若已有日志约定先 grep `getLogger` 抄风格）
- 兜底真正追加了 subtask 时：`logger.info("split-fallback: %d 子句追加, input=%.30r", n, user_input)`
- 两个规则修正（`_recover_pending` / `_pref_only_correction`）实际改写结果时各加一条
  同级 info 日志（改写前后意图）——为将来评估「规则层触发率」留数据，本票不做统计

### 3. 测试 `tests/test_intent_split.py`

先读现有测试抄注入方式（假分类器/monkeypatch），新增：
- `test_split_fallback_no_recursion`：构造子句内仍含「，另外」的输入，断言子句分类
  被调用时不再触发二次拆分（monkeypatch `_split_subtasks` 计数，或断言假分类器
  被调用的次数封顶）
- `test_split_fallback_depth_param_default`：外部调用 `classify(recent, text)` 不需要
  传 `_depth`（签名兼容）

## 不做

- 改变拆分规则本身（标记词表/分隔符逻辑不动）
- 规则层触发率统计报表（只埋日志点）

## 验收

- [ ] `uv run pytest tests/test_intent_split.py tests/test_intent.py -q` 全绿
- [ ] 门禁四步全绿（`scripts/gate.sh`）
- [ ] 黄金集回归：`uv run python scripts/eval/run.py --set intent --threshold 1.0`
      仍 100%（需 .env 密钥；护栏只封递归，不改单层行为，掉分即引入了 bug）

## Answer

已实现（递归护栏 + 触发率日志）：

- `intent.py`：`classify()` 加 keyword-only 参数 `_depth: int = 0`；拆分兜底仅 `_depth==0` 执行，
  子句分类以 `_depth=1` 调用，递归深度封顶 1。三个规则改写点（split-fallback /
  pref-only-lock / recover-pending）各加一条 `logger.info`。
- `tests/test_intent_split.py` 新增 2 测试：`test_split_fallback_no_recursion`
  （spy 计数断言 `_split_subtasks` 只调一次，无护栏会调 1+N 次）、
  `test_split_fallback_depth_param_default`（签名 keyword-only + 默认 0）。

验证：`test_intent_split.py + test_intent.py` 32 passed；ruff/mypy 对改动文件 0 警告。

实现中修正了票的一个过度陈述：原票称「子句仍含标记会继续拆、深度不可控」，经分析
`_split_subtasks` 的分段构造保证子句内不存在「标记+前置分隔符」，自然深度就是 1；
护栏的价值在于显式化不变量 + 防未来 `_split_subtasks` 语义变化，非修复真实死循环。
