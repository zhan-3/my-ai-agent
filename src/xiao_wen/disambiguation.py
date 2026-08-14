"""轻量消歧：意图层真歧义 → 带选项反问（多轮，不加图回边）

只对歧义子集反问：纯规则启发式（不烧 LLM），命中返回反问问题文本；
问题作为本轮答案（写回记忆），下一轮用户回答带 recent 上下文重新分类。
未命中返回 None（原路由路径不变）。

歧义子集 v1（两个触发器，意图 + 模式双重匹配，降低误触发）：
- A 航班/车次信息类：被分类成「行程规划」但输入是信息查询（查/有没有/几点），
  且非订/买动作 —— 区分「查时刻信息」与「规划含航班的行程」
  （BUG-003 统一归行程规划后，纯信息查询会被误当规划任务）
- B 咨询建议类：被分类成「其他」但输入是差旅咨询（比较好/推荐/哪家）——
  区分「查公司差旅标准（政策）」与「按偏好规划行程推荐」
"""

import re

# 触发器 A：信息查询动词 × 交通出行词 × 非订买动作
_FLIGHT_INFO = re.compile(r"(查|有没有|还有没有|几点|时刻|时间|班次|趟)")
_FLIGHT_TRAVEL = re.compile(r"(航班|机票|飞机|车次|高铁|火车|动车|班车)")
_FLIGHT_BOOKING = re.compile(r"(订|买|预订|购票)")

# 触发器 B：咨询建议表达 × 差旅语境
_ADVICE = re.compile(r"(比较好|推荐|哪家|怎么选|应该怎么|注意什么|住哪里|好一点)")
_TRAVEL_CTX = re.compile(r"(住宿|酒店|出差|出行|交通|住|机票)")

# 触发器 C：消歧反问的选项应答（确定性，不依赖 LLM 意图）
_OPTION_ONE = re.compile(r"^[①1][、.。:：]?$")
_OPTION_TWO = re.compile(r"^[②2][、.。:：]?$")
# recent 里出现该片段即判定「上一轮反问过航班消歧」
_FLIGHT_QUESTION_MARK = "①查航班/车次时刻信息"

# 选项①的诚实答复：系统无航班/车次实时工具，不把信息查询静默变成规划追问
_INFO_UNSUPPORTED = "暂不支持实时航班/车次查询；如需规划含航班/车次的出行，请告诉我出发日期和目的城市。"


def clarify(user_input: str, intent_name: str, recent: str = "") -> str | None:
    """命中歧义子集返回反问问题（带 ①② 选项），否则 None。

    user_input: 当前用户输入（原始文本）；intent_name: classify 结果意图；
    recent: 最近对话（用于识别用户在消歧反问后的选项应答）。
    """
    # 规则 C：上一轮反问过航班消歧 → 用户直接答选项（①查时刻→诚实不支持，②放行正常意图解析）
    if _OPTION_ONE.match(user_input.strip()) and _FLIGHT_QUESTION_MARK in recent:
        return _INFO_UNSUPPORTED
    if _flight_ambiguous(user_input, intent_name):
        return "你是想①查航班/车次时刻信息，还是②规划含这段出行的行程？"
    if _advice_ambiguous(user_input, intent_name):
        return "你是想①查公司差旅住宿/交通标准（政策），还是②按你的偏好规划行程、推荐住宿？"
    return None


def _flight_ambiguous(text: str, intent: str) -> bool:
    if intent != "行程规划":
        return False
    if not (_FLIGHT_INFO.search(text) and _FLIGHT_TRAVEL.search(text)):
        return False
    return not _FLIGHT_BOOKING.search(text)


def _advice_ambiguous(text: str, intent: str) -> bool:
    if intent != "其他":
        return False
    return bool(_ADVICE.search(text) and _TRAVEL_CTX.search(text))
