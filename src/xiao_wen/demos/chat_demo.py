"""会话演示：单意图回归 + 多意图并行（真实产品路径 session.chat）

跑法：uv run python -m xiao_wen.demos.chat_demo
依赖：.env（DEEPSEEK_* + DASHSCOPE_API_KEY）；POSTGRES_URL（记忆后端）

案例顺序：
  ① 偏好新增（长期记忆写入）
  ② 常驻城市更新（覆盖同类别）
  ③ 行程规划：不说出发城市 → 用常驻城市补全
  ④ 多意图并行：知识问答 + 联网查询
  ⑤ 多意图并行：历史查询 + 联网查询
  ⑥ 指代消解：靠短期记忆理解「那上海呢」= 问天气
  ⑦ 历史查询（读长期记忆）
  ⑧ 外部扩展子 Agent：差旅统计（第七意图，由注册表动态发现）
  ⑨ 边界（应归「其他」）
"""

if __name__ == "__main__":
    from xiao_wen.session import chat

    demo = [
        "我不吃辣，住宿喜欢安静",
        "我现在常住上海",
        "10月8日去北京开会4天",
        "帮我查下出差住宿标准是什么，顺便看看北京今天天气怎么样",
        "我上次的行程是什么，还有上海明天天气怎么样",
        "那上海呢",
        "我上次的行程是什么",
        "统计一下我的出差情况",
        "这个暑假去哪里玩",
    ]
    for t in demo:
        print("=" * 60)
        print(f"用户：{t}")
        r = chat(t)
        print(f"意图：{r.intent}（{r.reason}）")
        print(r.answer)
