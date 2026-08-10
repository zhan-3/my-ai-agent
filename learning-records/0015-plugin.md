# LR-0015 · 插件化架构（加分项 C 完成）

**日期**：2026-08-10（第十四课）
**主题**：插件系统——动态发现 / 懒加载 / 渐进式披露 / 热插拔
**背景**：用户问「加分项 C 可行吗」→ 详细讲更改方案 → 用户先问 git 提交再动手 → 首次提交 ba6ad56（64 文件）→ 实现加分项 C

## 关键决策与事实

1. **插件公约**：每个插件 = `INTENT` + `DESCRIPTION`（元数据）+ `run(query) -> str`（统一接口）；主管只认公约，不关心内部
2. **三机制**：
   - 自动扫描注册：`discover()` glob plugins/*.py 读元数据
   - 渐进式披露：`read_metadata()` 用 **AST 解析**（ast.parse + literal_eval），不执行模块——哨兵日志实证发现阶段零加载
   - 懒加载：`load_plugin()` 派发时才 exec_module + `_loaded` 缓存
3. **热插拔演示**：运行中写 plugins/summary.py → rediscover → 主管提示词自动多「差旅总结」→ 命中路由（主管代码零改动）
4. **动态性的代价**：Intent.intent 从 Literal[六类] 变 str + 运行时校验（不在 manifest 落「其他」）——插件化固有权衡
5. **踩坑**：① `@tool` 装饰后 get_weather 是 StructuredTool 不可直接调用 → `.func` 取原函数；② 0012 边界答复 `return "..."` 换行拼接被 Python 当两语句（后半句被丢弃）→ 括号包裹修复——**return 换行拼接必须加括号**
6. **mypy**：homework + plugins 16 文件 0 错误（importlib spec None 检查 ×2、assert isinstance(r, Intent)、model 用 os.environ 非 getenv）
7. **git**：首次提交 ba6ad56（基础项 + 加分项 A/B + README + 课程 1-13 + mypy）；插件化成果待提交

## 实测（4 幕全通）
1. 动态发现：3 插件零执行 ✅ 2. 懒加载：policy/weather 哨兵 + 真天气 29.7°C ✅ 3. 热插拔：自动认识「差旅总结」返回真实档案 ✅ 4. 边界 ✅

**加分项 C 完成**（自动扫描注册 + 懒加载 + 渐进式披露 + 热插拔）✅

## 学生表现
- 问「可行吗」→ 要详细更改方案 → 认可后动手——先理解再执行的学习模式
- 主动问 git 提交时机（工程习惯成长）

## 下一步
- 提交插件化成果；README 更新（C ✅、目录、§6.9、术语表）
- 候选：行程校验层、sqlite、演示录屏收尾、打包提交
