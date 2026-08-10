# LR-0016 · 工程稳定性（加分项 D 完成）

**日期**：2026-08-10（第十五课）
**主题**：重试 / 超时 / 熔断 / 异常兜底 / 日志 / 健康检查
**背景**：用户选「继续 D」→ 精读作业文档（D 六项：重试/超时/熔断/异常兜底/日志/健康检查）→ 实现稳定性层

## 关键决策与事实

1. **稳定性层独立模块 `homework/stability.py`**：`with_retry`（指数退避，可配熔断器）/ `CircuitBreaker`（三态 closed→open→half_open）/ `safe_call`（异常兜底）/ `logger`（双写 stdout+文件）/ `health_check()`（五项自检）
2. **LangChain 内置能力**：ChatOpenAI `max_retries=2` + `timeout=30` 加到 0010/0011/0012 的 llm 配置（纯加法；0011 通过 importlib 复用 0010 的 llm 自动继承）
3. **演示 `0013_stability.py` 四幕**：幕1 指数退避重试（0.3→0.6s）；幕2 熔断（第 4 次 0ms 快速失败 + half_open 试探）；幕3 真实故障注入；幕4 健康检查 5 项全 ✅
4. **关键发现**：monkeypatch `base.llm` 不生效——模型链（prompt | llm.with_structured_output）构造时捕获 llm 引用；故障注入必须重建模型链。推论：**稳定性层包调用点，不指望内部依赖可换**
5. **踩坑**：① 幕2 显示条件 dt<0.05ms 把前 3 次误标"熔断打开"→ 改按异常消息判断；② 幕3 state 缺 "recent" 键（0010 classify 需 recent）→ KeyError 而非认证失败，补键后打出真实 401
6. **实测证据**：坏 key 注入 → 裸调用真实 401×2（内置重试）+ AuthenticationError 527ms 崩溃 vs safe_call 降级文案 281ms 系统未崩
7. **mypy**：homework + plugins 18 文件 0 错误；0010 回归 11 行关键输出全在（llm 参数变更无行为影响）

**加分项 D 完成**（六件套全实现 + 真实故障注入演示）✅

## 学生表现
- 选 D 而非直接收尾——主动补齐工程稳定性
- 上轮已养成「先确认要求再动手」习惯（问 C 时读文档）

## 下一步
- 提交；README 更新（D ✅、§6.10、术语表补「熔断/超时/重试/健康检查」）
- 候选：行程校验层、sqlite、演示录屏收尾、打包提交
