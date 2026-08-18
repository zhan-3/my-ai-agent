"""有界主管 Agent Loop：模型选择子 Agent，观察结果后继续决策。"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from xiao_wen.llm import get_llm
from xiao_wen.plugin_registry import discover, load_agent

Emit = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class LoopLimits:
    max_steps: int = 6
    max_tool_calls: int = 6
    timeout_seconds: float = 60
    max_tokens: int = 12_000
    max_repeat_calls: int = 2


_SYSTEM = """你是晓问的主管 Agent，只处理企业差旅。
你可以直接回答简单问候；其他任务应调用最合适的子 Agent，并在看到结果后再决定是否继续调用。
政策、报销、住宿标准、预订流程（订票/改签/退票/购票渠道/座位等级）必须调用知识问答；天气、汇率、空气质量必须调用联网查询；
新行程或补全行程调用行程规划；只有用户明确查询已保存的记录时才调用历史查询。
票务执行（订票、改签、退票、查车次/余票/票价）：晓问不代购、不提供实时票务查询，一律引导用户通过晓问商旅平台（travel.xiaowen.com）办理；
预订流程与规则等知识调用知识问答。
仅陈述常住城市、餐饮、住宿等偏好而未要求规划时，只调用偏好记录，绝不自行调用行程规划。
若存在活跃行程任务，只有本轮信息直接回答 missing 列表中的缺项时才继续调用行程规划；
“我现在常住某地”既要调用偏好记录，也要继续调用行程规划。餐饮/住宿偏好若不是当前缺项，属于独立插入请求，
只调用偏好记录并提醒活跃行程仍保留，不要调用行程规划。政策或实时查询也可以暂时打断行程。
不得编造政策、天气、车次、订单或购买结果。调用参数 request 应包含本轮原话和必要的活跃任务信息，
成为子 Agent 可独立理解的完整请求。最终回答直接写给用户的话术，只能使用已观察到的结果；
禁止输出推理、计划或元叙述（如「我需要先…」「好的，目前…」「根据…结果，我…」）；
行程规划提示缺项时，原样给出缺项清单即可，不要复述判断过程。
"""

_POLICY_WORDS = ("政策", "报销", "住宿标准", "差旅标准", "审批", "订票", "购票", "改签", "退票")
_WEATHER_WORDS = ("天气", "气温", "下雨", "降雨", "台风", "雷暴")
_OUTPUT_KEYS = ("plan", "stats", "history", "task_update", "failure")


class AgentLoop:
    """单一运行接口；模型、注册中心和取消信号均可注入。"""

    def __init__(
        self,
        *,
        model: Any | None = None,
        discover_agents: Callable[[], list[dict]] = discover,
        load_child: Callable[[str], Any] = load_agent,
        limits: LoopLimits | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self._model = model
        self._discover = discover_agents
        self._load = load_child
        self._limits = limits or LoopLimits()
        self._cancelled = cancelled

    def run(self, turn: dict[str, Any], emit: Emit | None = None) -> dict[str, Any]:
        """运行一轮并返回兼容会话契约的结果 dict。"""
        send = emit or (lambda _event: None)
        manifest = self._discover()
        tools, intents = _tool_specs(manifest)
        model = (self._model or get_llm()).bind_tools(tools)
        prompt = _prompt(turn)
        messages: list[Any] = [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        outputs: list[tuple[str, dict[str, Any]]] = []
        repeats: Counter[str] = Counter()
        completed: set[str] = set()
        tool_count = 0
        tokens = _estimate_tokens(_SYSTEM) + _estimate_tokens(prompt)
        deadline = time.monotonic() + self._limits.timeout_seconds

        send({"type": "run_start"})
        for step in range(1, self._limits.max_steps + 1):
            failure = self._boundary_failure(deadline, tokens)
            if failure:
                return _failed(failure, send, messages)

            send({"type": "turn_start", "step": step})
            raw = model.invoke(messages)
            message = raw if isinstance(raw, AIMessage) else AIMessage(content=str(raw))
            messages.append(message)
            tokens += _message_tokens(message)
            failure = self._boundary_failure(deadline, tokens)
            if failure:
                return _failed(failure, send, messages)
            send({"type": "assistant", "step": step, "content": "" if message.tool_calls else _text(message)})

            if not message.tool_calls:
                result = _result(turn["user_input"], _text(message), outputs, messages)
                send({"type": "final", **result})
                return result

            for tool_call in message.tool_calls:
                tool_count += 1
                failure = self._boundary_failure(deadline, tokens)
                if failure:
                    return _failed(failure, send, messages)
                name = tool_call.get("name", "")
                call_id = tool_call.get("id") or f"step-{step}"
                intent = intents.get(name)
                request = str((tool_call.get("args") or {}).get("request", "")).strip()
                signature = json.dumps([intent, request], ensure_ascii=False)
                repeats[signature] += 1
                send({"type": "agent_start", "agent": intent or name, "request": request, "tool_call_id": call_id})
                post_failure: dict[str, Any] | None = None
                outcome: dict[str, Any]

                if intent is None:
                    outcome = {"error": f"未知子 Agent：{name}"}
                    is_error = True
                elif not request:
                    outcome = {"error": "request 不能为空"}
                    is_error = True
                elif tool_count > self._limits.max_tool_calls:
                    outcome = {"error": "本轮已达到子 Agent 调用上限"}
                    is_error = True
                    post_failure = {
                        "code": "agent_limit",
                        "message": "本轮已达到子 Agent 调用上限，请缩小问题范围后重试。",
                        "retryable": True,
                    }
                elif intent == "行程规划" and not _trip_requested(turn):
                    outcome = {"error": "用户没有请求新行程，也没有提供活跃行程当前所缺的信息"}
                    is_error = True
                elif signature in completed:
                    outcome = {"error": "相同子 Agent 请求已执行过，不会重复产生副作用"}
                    is_error = True
                elif repeats[signature] > self._limits.max_repeat_calls:
                    outcome = {"error": "相同子 Agent 请求已达到失败重试上限"}
                    is_error = True
                else:
                    try:
                        if intent in {"偏好记录", "行程规划"}:
                            completed.add(signature)
                        raw_outcome = self._load(intent).run(
                            {
                                **turn,
                                "user_input": turn["user_input"],
                                "agent_request": request,
                                "_cancelled": self._cancelled,
                                "_defer_writes": True,
                            }
                        )
                        outcome = _normalize_outcome(raw_outcome)
                        post_failure = self._boundary_failure(deadline, tokens)
                        if post_failure:
                            outcome = {"error": post_failure["message"], "error_type": post_failure["code"]}
                            is_error = True
                        else:
                            outputs.append((intent, outcome))
                            completed.add(signature)
                            is_error = False
                    except Exception as error:
                        outcome = {
                            "error": "子 Agent 执行失败，请选择重试、降级或结束。",
                            "error_type": type(error).__name__,
                        }
                        is_error = True

                send(
                    {
                        "type": "agent_result",
                        "agent": intent or name,
                        "tool_call_id": call_id,
                        "is_error": is_error,
                        "result": outcome,
                    }
                )
                serialized = json.dumps(_model_observation(intent or name, outcome), ensure_ascii=False, default=str)
                tokens += _estimate_tokens(serialized)
                messages.append(ToolMessage(content=serialized, tool_call_id=call_id, name=name))
                if post_failure:
                    return _failed(post_failure, send, messages)

        return _failed(
            {"code": "agent_limit", "message": "本轮已达到最大处理步数，请缩小问题范围后重试。", "retryable": True},
            send,
            messages,
        )

    def _boundary_failure(self, deadline: float, tokens: int) -> dict[str, Any] | None:
        if self._cancelled():
            return {"code": "cancelled", "message": "请求已取消。", "retryable": False}
        if time.monotonic() >= deadline:
            return {"code": "agent_timeout", "message": "本轮处理超时，请稍后重试。", "retryable": True}
        if tokens >= self._limits.max_tokens:
            return {
                "code": "agent_token_limit",
                "message": "本轮已达到 token 上限，请缩小问题范围。",
                "retryable": True,
            }
        return None


def _trip_requested(turn: dict[str, Any]) -> bool:
    text = str(turn.get("user_input", ""))
    active = turn.get("active_task")
    if isinstance(active, dict) and active.get("intent") == "行程规划":
        from xiao_wen.reference_data import KNOWN_CITIES

        missing = active.get("missing") or []
        if "出发城市" in missing and _provides_origin(text):
            return True
        if any("天数" in str(item) for item in missing) and re.search(r"\d+\s*天", text):
            return True
        if any("日期" in str(item) for item in missing) and re.search(r"\d|今天|明天|后天|下周", text):
            return True
        return any("目的" in str(item) for item in missing) and any(city in text for city in KNOWN_CITIES)
    return any(word in text for word in ("规划", "安排行程", "行程安排")) or bool(
        re.search(r"(?:去|到|前往).{1,12}(?:开会|出差|拜访|培训)", text)
    )


def _provides_origin(text: str) -> bool:
    """用户补全出发城市：从X出发 / X出发 / 常住X / 纯城市名（含非白名单城市如临沂）。

    门禁不能只认 KNOWN_CITIES 白名单：临沂等城市不在 20 城名单里，
    「从临沂出发」会被误判为「没有补全出发城市」而反复拦截行程规划。
    """
    from xiao_wen.trip_planner import _detect_home_city, _looks_like_city_name

    if _detect_home_city(text) or _looks_like_city_name(text):
        return True
    return bool(re.search(r"从\S{1,8}出发", text))


def _model_observation(agent: str, outcome: dict[str, Any]) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "agent": agent,
        **{key: outcome[key] for key in ("answer", "error", "error_type") if key in outcome},
    }
    for key in ("policy_status", "realtime_status", "ticket_status", "failure"):
        if key in outcome:
            observation[key] = outcome[key]
    sources = outcome.get("sources")
    if isinstance(sources, list):
        observation["evidence_ids"] = [
            source["evidence_id"]
            for source in sources
            if isinstance(source, dict) and isinstance(source.get("evidence_id"), str)
        ]
    return observation


def _normalize_outcome(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("answer"), str) or not value["answer"].strip():
        raise TypeError("子 Agent 必须返回含非空 answer 的 dict")
    for key in ("policy_status", "realtime_status", "ticket_status"):
        if key in value and not isinstance(value[key], str):
            raise TypeError(f"子 Agent 字段 {key} 必须是字符串")
    if "sources" in value and not isinstance(value["sources"], list):
        raise TypeError("子 Agent 字段 sources 必须是列表")
    if "memory_writes" in value and not isinstance(value["memory_writes"], list):
        raise TypeError("子 Agent 字段 memory_writes 必须是列表")
    return value


def _tool_specs(manifest: list[dict]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    tools = []
    intents = {}
    for index, item in enumerate(manifest):
        name = f"agent_{index}"
        intents[name] = item["INTENT"]
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"{item['INTENT']}：{item['DESCRIPTION']}",
                    "parameters": {
                        "type": "object",
                        "properties": {"request": {"type": "string", "description": "完整、可独立执行的用户请求"}},
                        "required": ["request"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    return tools, intents


def _prompt(turn: dict[str, Any]) -> str:
    active = turn.get("active_task")
    active_text = json.dumps(active, ensure_ascii=False) if active else "无"
    return (
        f"最近对话：\n{turn.get('recent', '无')}\n\n活跃任务：\n{active_text}\n\n用户本轮请求：\n{turn['user_input']}"
    )


def _text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content.strip()
    return "".join(str(part.get("text", "")) for part in message.content if isinstance(part, dict)).strip()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _message_tokens(message: AIMessage) -> int:
    # 统一按字符估算，禁用 usage_metadata：其 total_tokens 是本次请求的累计值，
    # 做增量累加会几何虚增（曾假性触发 agent_token_limit）。tool_calls 一并估算。
    n = _estimate_tokens(_text(message))
    for tool_call in getattr(message, "tool_calls", None) or []:
        n += _estimate_tokens(json.dumps(tool_call, ensure_ascii=False, default=str))
    return n


def _result(
    user_input: str,
    answer: str,
    outputs: list[tuple[str, dict[str, Any]]],
    messages: list[Any],
) -> dict[str, Any]:
    by_intent = dict(outputs)
    latest = list(by_intent.items())
    result: dict[str, Any] = {
        "answer": answer or "（暂无回复，请换个说法再试一次）",
        "intent": outputs[-1][0] if outputs else "其他",
        "reason": "主管根据子 Agent observation 完成" if outputs else "主管直接回答",
        "transcript": _transcript(messages[1:]),
    }
    for key in _OUTPUT_KEYS:
        result[key] = next((out.get(key) for _, out in latest if out.get(key) is not None), None)

    # 行程规划追问缺项（NeedsInfo → task_update.action == "set"）：最终答案直接复用子 Agent 的
    # 缺项话术，禁止主管重写——重写会把思维链暴露给用户（曾输出「好的，目前没有常驻城市偏好…
    # 我需要向用户确认」这类推理中间文本）。
    for _, out in latest:
        update = out.get("task_update")
        if isinstance(update, dict) and update.get("action") == "set":
            child_answer = out.get("answer")
            if isinstance(child_answer, str) and child_answer.strip():
                result["answer"] = child_answer
            break

    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, out in latest:
        raw_sources = out.get("sources")
        if not isinstance(raw_sources, list):
            continue
        for source in raw_sources:
            if not isinstance(source, dict) or not isinstance(source.get("evidence_id"), str):
                continue
            evidence_id = source["evidence_id"]
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            sources.append(source)
    result["sources"] = sources
    result["memory_writes"] = [
        write for _, out in latest for write in (out.get("memory_writes") or []) if isinstance(write, dict)
    ]
    allowed_statuses = {"unavailable", "ambiguous", "stale", "grounded", "not_found"}
    statuses = [str(out["policy_status"]) for _, out in latest if out.get("policy_status") in allowed_statuses]
    if statuses:
        priority = {"unavailable": 5, "ambiguous": 4, "stale": 3, "grounded": 2, "not_found": 1}
        result["policy_status"] = max(statuses, key=lambda status: priority[status])

    needs_policy_gate = any(word in user_input for word in _POLICY_WORDS)
    needs_weather_gate = any(word in user_input for word in _WEATHER_WORDS)
    if needs_policy_gate:
        policy = by_intent.get("知识问答") or by_intent.get("行程规划") or {}
        if not policy:
            result["answer"] = "该问题需要先查询公司知识库；在没有政策证据时我不能给出具体标准。"
            result["policy_status"] = "not_found"
            return result
        if result.get("policy_status") == "grounded" and not sources:
            result["answer"] = "政策结果缺少可追溯证据，因此不能提供具体标准。"
            result["policy_status"] = "not_found"
            return result
    if needs_weather_gate:
        web = by_intent.get("联网查询", {})
        if "行程规划" not in by_intent and web.get("realtime_status") not in {
            "grounded",
            "unavailable",
            "invalid",
        }:
            result["answer"] = "暂时无法获取可靠天气信息，请稍后重试。"
            return result
    if needs_policy_gate or needs_weather_gate:
        exact_answers: list[str] = []
        for _, out in latest:
            child_answer = out.get("answer")
            if isinstance(child_answer, str):
                exact_answers.append(child_answer)
        result["answer"] = "\n\n".join(dict.fromkeys(exact_answers)) or result["answer"]
    return result


def _transcript(messages: list[Any]) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            transcript.append({"role": "user", "content": message.content})
        elif isinstance(message, AIMessage):
            transcript.append(
                {
                    "role": "assistant",
                    "content": "" if message.tool_calls else _text(message),
                    "tool_calls": list(message.tool_calls),
                }
            )
        elif isinstance(message, ToolMessage):
            transcript.append(
                {
                    "role": "tool",
                    "name": message.name,
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
    return transcript


def _failed(failure: dict[str, Any], emit: Emit, messages: list[Any]) -> dict[str, Any]:
    result = {
        "answer": failure["message"],
        "intent": "",
        "reason": failure["code"],
        "failure": failure,
        "sources": [],
        "transcript": _transcript(messages[1:]),
    }
    emit({"type": "error", **failure})
    return result
