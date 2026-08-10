"""极简文件记忆存储（单用户演示版）—— 短期 + 长期两层记忆
真实产品：短期记忆用 LangGraph checkpointer（thread 维度、数据库持久化、随时恢复）；
长期记忆用 store（namespace/key 组织、JSON 文档、语义搜索）。这里用 JSON 文件演示
「存储-读取」概念，后续可平移到真实存储。

数据文件：data/memory.json（已在 .gitignore 中，不进 git）
结构：
- messages:     短期记忆（最近 N 轮对话，thread 维度）
- preferences:  长期记忆-偏好（含追加/覆盖：is_update 时替换同类别旧条目）
- itineraries:  长期记忆-历史行程（可统计常用目的地）
"""
import json
import time
from collections import Counter
from pathlib import Path

MEMORY_PATH = Path(__file__).resolve().parent.parent / "data" / "memory.json"


def _default():
    return {"preferences": [], "itineraries": [], "messages": []}


def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _default()
    with open(MEMORY_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_memory(mem: dict) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


# ---------- 短期记忆：最近 N 轮对话（thread 维度） ----------
def add_message(role: str, content: str) -> dict:
    mem = load_memory()
    rec = {"role": role, "content": content, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    mem["messages"].append(rec)
    save_memory(mem)
    return rec


def get_recent_messages(n: int = 6) -> list[dict]:
    """最近 n 条消息（按时间正序）"""
    return load_memory()["messages"][-n:]


def format_recent_messages(n: int = 6) -> str:
    """格式化为给 LLM 看的文本（供意图识别注入，hot path 注入要克制）"""
    msgs = get_recent_messages(n)
    if not msgs:
        return "无"
    lines = [f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:80]}"
             for m in msgs]
    return "\n".join(lines)


# ---------- 长期记忆：偏好（追加 / 覆盖） ----------
def add_or_update_preference(category: str, content: str, is_update: bool = False) -> dict:
    """偏好写入。is_update=True 时替换同类别旧条目（如「我现在常住上海」更新常驻城市）"""
    mem = load_memory()
    if is_update:
        mem["preferences"] = [p for p in mem["preferences"] if p["category"] != category]
    rec = {"category": category, "content": content,
           "ts": time.strftime("%Y-%m-%d %H:%M")}
    mem["preferences"].append(rec)
    save_memory(mem)
    return rec


def get_preferences(category: str | None = None) -> list[dict]:
    mem = load_memory()
    prefs = mem["preferences"]
    if category:
        return [p for p in prefs if p["category"] == category]
    return prefs


def get_home_city() -> str | None:
    """常驻城市（长期信息，用于行程规划时补出发城市——「下次直接说去哪别再傻问」）"""
    for p in reversed(get_preferences("常驻城市")):
        return p["content"]
    return None


def get_common_destinations(n: int = 3) -> list[str]:
    """常用目的地（从历史行程统计，加分项「出差习惯」）"""
    its = get_itineraries()
    cities: list[str] = []
    for i in its:
        c = i.get("to_city")
        if isinstance(c, str) and c not in ("待定", "未知"):
            cities.append(c)
    return [c for c, _ in Counter(cities).most_common(n)]


# ---------- 长期记忆：历史行程 ----------
def add_itinerary(facts: dict, summary: str) -> dict:
    mem = load_memory()
    rec = {**facts, "summary": summary, "ts": time.strftime("%Y-%m-%d %H:%M")}
    mem["itineraries"].append(rec)
    save_memory(mem)
    return rec


def get_itineraries() -> list[dict]:
    return load_memory()["itineraries"]


if __name__ == "__main__":
    # 自检：短期能存能读；偏好追加/覆盖；常驻城市
    add_message("user", "自检：你好")
    add_message("assistant", "自检：你好，有什么可以帮你？")
    print("recent:", format_recent_messages(4))
    add_or_update_preference("常驻城市", "自检：上海")
    add_or_update_preference("常驻城市", "自检：北京", is_update=True)  # 覆盖
    print("home:", get_home_city())
    print("prefs:", get_preferences())
