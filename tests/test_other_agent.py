"""「其他」子 Agent 确定性测试：取消行程链路（状态机副作用）与兜底话术。

覆盖 run() 全部 4 条路径：
  1. 无取消词 → 服务范围兜底话术（不落库、无 task_update）
  2. 有活跃任务（drafting 追问中）→ task_update cancel
  3. 取消已确定行程：请求提到城市优先匹配，否则取最近行程
  4. 无行程可取消 → 明确空态
"""

import xiao_wen.dialogue
import xiao_wen.memory
from xiao_wen.agents import other_agent


def test_no_cancel_word_returns_business_scope_fallback():
    """路径 1：非取消请求归「其他」兜底，不落库、不带 task_update。"""
    result = other_agent.run({"user_input": "帮我规划五一去三亚玩5天的行程"})
    assert "不在企业差旅助手的服务范围内" in result["answer"]
    assert "task_update" not in result


def test_cancel_with_active_task_returns_cancel_update(monkeypatch):
    """路径 2：取消缺项追问中的 drafting（活跃任务）→ task_update = cancel。"""
    result = other_agent.run(
        {
            "user_input": "算了不去了",
            "active_task": {"intent": "行程规划", "missing": ["出发城市"]},
            "user_id": "u1",
        }
    )
    assert "已取消刚才未完成的行程" in result["answer"]
    assert result["task_update"] == {"action": "cancel"}


def test_cancel_upcoming_trip_matches_city(monkeypatch):
    """路径 3a：请求提到城市 → 匹配对应行程并取消（真实调 cancel_trip 落库）。"""
    trips = [
        {"id": 1, "to_city": "北京", "from_city": "上海", "start_date": "2026-09-01"},
        {"id": 2, "to_city": "广州", "from_city": "深圳", "start_date": "2026-09-02"},
    ]
    cancelled = []

    def fake_get_trips(**kwargs):
        return trips

    def fake_cancel_trip(trip_id, **kwargs):
        cancelled.append(trip_id)
        return True

    monkeypatch.setattr(xiao_wen.memory, "get_trips", fake_get_trips)
    monkeypatch.setattr(xiao_wen.memory, "cancel_trip", fake_cancel_trip)
    result = other_agent.run({"user_input": "取消北京那个行程", "user_id": "u1"})
    assert cancelled == [1]  # 命中城市北京 → id 1
    assert "已取消「北京」的行程" in result["answer"]
    assert result["task_update"] == {"action": "cancel"}


def test_cancel_falls_back_to_latest_trip(monkeypatch):
    """路径 3b：请求未提城市 → 取最近行程取消。"""
    monkeypatch.setattr(xiao_wen.memory, "get_trips", lambda **kw: [])
    monkeypatch.setattr(xiao_wen.memory, "cancel_trip", lambda trip_id, **kw: trip_id == 9)
    result = other_agent.run(
        {
            "user_input": "不去了",
            "user_id": "u1",
            "latest_trip": {"id": 9, "to_city": "成都", "start_date": "2026-09-03"},
        }
    )
    assert "已取消「成都」的行程" in result["answer"]


def test_cancel_no_trip_returns_explicit_empty(monkeypatch):
    """路径 4：没有可取消的行程 → 明确空态（不编造「已取消」）。"""
    monkeypatch.setattr(xiao_wen.memory, "get_trips", lambda **kw: [])
    monkeypatch.setattr(xiao_wen.memory, "cancel_trip", lambda trip_id, **kw: False)
    result = other_agent.run(
        {
            "user_input": "取消",
            "user_id": "u1",
            "latest_trip": None,
        }
    )
    assert "没有找到可取消的行程" in result["answer"]
    assert "task_update" not in result


def test_cancel_trip_store_failure_returns_empty(monkeypatch):
    """路径 3b 变体：cancel_trip 落库失败（返回 False）→ 不谎报已取消。"""
    monkeypatch.setattr(xiao_wen.memory, "get_trips", lambda **kw: [])
    monkeypatch.setattr(xiao_wen.memory, "cancel_trip", lambda trip_id, **kw: False)
    result = other_agent.run(
        {
            "user_input": "取消",
            "user_id": "u1",
            "latest_trip": {"id": 5, "to_city": "杭州", "start_date": "2026-09-04"},
        }
    )
    assert "没有找到可取消的行程" in result["answer"]
