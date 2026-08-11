# LR-0017 · 评测与测试（加分项 E 完成）

**日期**：2026-08-10（第十六课）
**主题**：pytest 自动化回归——分层测试 / 数据隔离 / 参数化 / AST 零执行测试
**背景**：用户问「E测试怎么搞」（网络抖动连发"继续"后恢复）→ 精读要求（典型用例/对意图记忆RAG规划验证/自动化回归）→ pytest 固化

## 关键决策与事实

1. **分层测试**：单元层 26 个（记忆/行程纯逻辑/插件注册中心/稳定性层，无 LLM，秒级）+ 集成层 8 个（意图 7 用例 + 端到端记忆闭环，真 LLM，`-m integration` 显式跑）
2. **配置**：`uv add --dev pytest`（9.1.1）；pyproject `[tool.pytest.ini_options]` testpaths + markers 注册；mypy files 保持 ["homework"] 不含 tests
3. **数据隔离**：conftest autouse fixture `monkeypatch memory_store.MEMORY_PATH → tmp_path`，测试绝不碰 data/memory.json（发现 memory_store 无缓存，每次读文件，patch 全局即生效）
4. **参数化**：意图用例从 0004/0010 固化（含边界"三亚度假→其他"），parametrize 7 用例
5. **AST 零执行测试**：「加载即爆炸」假插件（raise 在 INTENT 前）→ discover 能读元数据但代码未执行——渐进式披露的实证测试
6. **测试踩坑 3 个**（真实 API 约束 vs 测试假设）：
   - TripRequest 有 hotel_pref/budget_pref 必填字段（无默认）→ pydantic 校验失败，读模型定义
   - add_or_update_preference 返回 dict 无 is_update 键 → 验证行为用 get_preferences 查询
   - CircuitBreaker.is_open 是 @property 惰性迁移 → sleep 后需先访问再断言
7. **实测**：单元层 26 passed / 集成层 8 passed（真 LLM 意图 7/7 含边界 + 端到端偏好→常驻城市补全→行程→历史→边界全通）

**加分项 E 完成**（典型用例 + 意图/记忆/规划验证 + 自动化回归）✅

## 学生表现
- 网络抖动连发"继续"，恢复后立即继续——不丢上下文
- 问「E测试怎么搞」是学习意图（想理解再动手）

## 下一步
- 提交；README 更新（E ✅、§6.11、目录 tests/、运行方式 pytest、§9 E→✅）
- 加分项全景：A✅ B✅ C✅ D✅ E✅ F✖
- 剩：演示录屏 + 打包提交（硬要求）；课程 0016 已开；LR 待提交
