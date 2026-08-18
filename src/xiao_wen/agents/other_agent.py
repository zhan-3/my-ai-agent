"""内置子 Agent：其他（兜底，多 Agent 架构的子 Agent 实体）

产品边界外的请求（个人休闲/旅游规划、非差旅问题）一律归此兜底。
"""

INTENT = "其他"
DESCRIPTION = (
    "以上都不像（个人休闲/旅游/度假规划、公司团建、非差旅问题）→ 其他（兜底）。"
    "个人度假（五一去三亚玩5天）不归行程规划。"
)


def run(state) -> dict:
    from xiao_wen.dialogue import task_update_clear

    if state.get("active_task") and any(word in state.get("user_input", "") for word in ("算了", "取消", "不要了")):
        return {"answer": "好的，已取消刚才未完成的行程。", "task_update": task_update_clear()}
    return {
        "answer": "抱歉，这不在企业差旅助手的服务范围内（如个人休闲旅游、非差旅问题）。"
        "当前仅支持：行程规划、偏好、历史行程、差旅政策、实时信息。"
    }
