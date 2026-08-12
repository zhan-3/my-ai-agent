"""内置子 Agent 包（xiao_wen.agents）

每个模块 = 一个可被注册中心动态发现的子 Agent 实体：
- INTENT / DESCRIPTION 模块级元数据（注册中心 AST 渐进式披露，派发前零加载）
- run(state) -> dict 统一子 Agent 接口
内置六子 Agent：行程规划 / 偏好记录 / 历史查询 / 知识问答 / 联网查询 / 其他。
"""
