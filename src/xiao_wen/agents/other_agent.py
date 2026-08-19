"""内置子 Agent：其他（兜底 + 取消行程，多 Agent 架构的子 Agent 实体）

产品边界外的请求（个人休闲/旅游规划、非差旅问题）一律归此兜底。
取消行程（放弃 drafting 或取消已确定的行程）也在此处理，因为它是对话级副作用，
需要落在行程生命周期状态机里，不能让主管直接编造「已取消」而不落库。
"""

INTENT = "其他"
DESCRIPTION = (
    "以上都不像（个人休闲/旅游/度假规划、公司团建、非差旅问题）→ 其他（兜底）。"
    "个人度假（五一去三亚玩5天）不归行程规划。"
    "用户要取消/放弃行程（说「算了」「不去了」「取消」「不要了」「放弃」）→ 其他。"
)

_CANCEL_WORDS = ("算了", "取消", "不要了", "不去了", "放弃")


def run(state) -> dict:
    from xiao_wen.dialogue import task_update_cancel
    from xiao_wen.memory import cancel_trip, get_trips

    request = str(state.get("agent_request") or state.get("user_input", ""))
    if not any(word in request for word in _CANCEL_WORDS):
        return {
            "answer": "抱歉，这不在企业差旅助手的服务范围内（如个人休闲旅游、非差旅问题）。"
            "当前仅支持：行程规划、偏好、历史行程、差旅政策、实时信息。"
        }

    # 1) 取消缺项追问中的 drafting（活跃任务）
    if state.get("active_task"):
        return {"answer": "好的，已取消刚才未完成的行程。", "task_update": task_update_cancel()}

    # 2) 取消已确定的行程（upcoming/completed）：优先匹配请求里提到的城市，否则取最近行程
    user_id = state.get("user_id") or state.get("session_id", "default")
    target = None
    for trip in get_trips(session_id=user_id):
        city = str(trip.get("to_city", ""))
        if city and city in request:
            target = trip
            break
    if target is None:
        target = state.get("latest_trip")
    if target and target.get("id") is not None and cancel_trip(target["id"], session_id=user_id):
        city = target.get("to_city", "")
        # 返回 cancel 信号：让主管复用本话术（不重写），并顺带清掉线程内残留 drafting
        return {"answer": f"好的，已取消「{city}」的行程。", "task_update": task_update_cancel()}
    return {"answer": "抱歉，没有找到可取消的行程。"}
