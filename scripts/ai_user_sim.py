#!/usr/bin/env python3
"""AI 用户模拟器：三层受控随机 × 真实后端对话素材收集

- 人设层：随机组合卡片（城市/身份/交通/住宿/风格）——语义合法多样性，一场一套
- 目标层：从意图池抽任务，LLM 围绕目标自然展开
- 表达层：概率分支（正常推进 / 顺便插请求 / 故意省略信息 / 指代前文）
- 记忆一致性：说过的偏好注入下一轮 prompt，避免自相矛盾
- 输出：JSONL，每轮 {persona, goal, user_input, assistant, intent, plan}
"""

import argparse
import json
import os
import random
import sys
import time

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

load_dotenv()

# ---------- 人设卡池 ----------
PERSONA_POOL = {
    "city": ["上海", "北京", "杭州", "广州"],
    "role": ["销售，常跑外勤", "技术，驻场支持", "行政，帮同事订票"],
    "transit": ["高铁", "飞机", "自驾"],
    "hotel": ["连锁酒店", "民宿", "高端酒店"],
    "style": ["简短直接", "啰嗦详细", "爱用口语（咋/呗/嗯呐）"],
}

# ---------- 目标池 ----------
GOAL_POOL = [
    "规划一次出差行程（去另一个城市开会 2-4 天）",
    "了解公司差旅政策（报销/餐补/住宿标准）",
    "回忆自己之前的出差历史（去过哪、住过哪）",
    "设置/更新自己的出差偏好（城市/交通/住宿）",
    "先规划行程，再问天气（多意图）",
    "先问政策，再规划行程（多意图）",
]

# ---------- 插话池（次要请求） ----------
SIDE_REQUEST_POOL = [
    "查一下目的地天气",
    "问一下当地有什么好玩的",
    "查一下回程日期有没有航班",
]

# ---------- 表达层分支 ----------
BEHAVIOR_BRANCHES = [
    (0.70, "normal"),
    (0.15, "side_request"),
    (0.10, "vague"),  # 故意省略关键信息（日期/城市）
    (0.05, "refer"),  # 用指代词接上下文
]


def pick_weighted(branches, rng):
    r = rng.random()
    acc = 0.0
    for weight, key in branches:
        acc += weight
        if r <= acc:
            return key
    return branches[-1][1]


def build_llm():
    return ChatOpenAI(
        model=os.environ["DEEPSEEK_MODEL"],
        base_url=os.environ["DEEPSEEK_BASE_URL"],
        api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
        temperature=0.8,
        timeout=30,
    )


def gen_user_line(llm, persona: dict, goal: str, facts: list, history: list, behavior: str, side: str | None) -> str:
    """LLM 生成用户下一句话（只输出用户话，或 [DONE]）"""
    sys_p = (
        f"你正在使用企业差旅助手（晓问）。你的人设：{persona['role']}，常驻{persona['city']}，"
        f"出差偏好{persona['transit']}、住{persona['hotel']}，说话风格{persona['style']}。\n"
        f"你的目标：{goal}。\n"
        f"你已知的事实（保持言行一致，不要自相矛盾）：{facts or '（暂无）'}\n"
        "规则：你只输出你这一轮要对助手说的一句到两句话，不要解释、不要带引号、不要扮演助手。"
        "不要重复你已经问过的问题或说过的话（除非助手要求你补充）。"
        "如果你认为目标已达成或没有可说的，只输出 [DONE]。"
    )
    if behavior == "normal":
        user_ins = "自然地继续推进你的目标，说下一句话。"
    elif behavior == "side_request":
        user_ins = f"继续说，并以「对了，顺便」自然插入一个次要请求：{side}"
    elif behavior == "vague":
        user_ins = "继续说，但故意省略关键信息（日期或城市），让助手追问。"
    else:  # refer
        user_ins = "用指代词继续对话（如「那酒店呢」「那天气呢」），不要重复全句。"
    history_text = "\n".join(f"用户: {u}\n助手: {a}" for u, a in history[-6:])
    user_p = f"对话历史：\n{history_text or '（还没有对话）'}\n\n本轮指示：{user_ins}\n\n你本轮要说的话："
    resp = llm.invoke([{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}])
    text = (resp.content or "").strip().strip('"')
    return text


def run_session(session_id: int, seed: int, base_url: str, token: str, max_turns: int, llm) -> list[dict]:
    rng = random.Random(seed)
    persona = {k: rng.choice(v) for k, v in PERSONA_POOL.items()}
    goal = rng.choice(GOAL_POOL)
    print(f"\n=== session {session_id} (seed={seed}) ===")
    print(
        f"人设: {persona['role']} / {persona['city']} / {persona['transit']} / {persona['hotel']} / {persona['style']}"
    )
    print(f"目标: {goal}")

    facts: list[str] = [f"常驻{city}" for city in [persona["city"]]]
    history: list[tuple[str, str]] = []
    turns: list[dict] = []
    headers = {"Authorization": f"Bearer {token}"}

    for turn in range(1, max_turns + 1):
        behavior = pick_weighted(BEHAVIOR_BRANCHES, rng)
        side = rng.choice(SIDE_REQUEST_POOL) if behavior == "side_request" else None
        line = gen_user_line(llm, persona, goal, facts, history, behavior, side)
        if not line or line == "[DONE]":
            print(f"  turn {turn}: 模拟器主动结束")
            break
        history.append((line, "…"))

        try:
            r = httpx.post(
                f"{base_url}/api/chat",
                json={"user_input": line},
                headers=headers,
                timeout=120,
            )
            body = r.json()
        except Exception as e:
            print(f"  turn {turn}: 后端调用失败 {e}")
            break
        answer = body.get("answer", "")
        intent = body.get("intent", "")
        plan = body.get("plan")
        # 事实回写：模拟器记住自己说过的关键偏好（粗提取）
        if "常驻" in line or "喜欢" in line or "偏好" in line:
            facts.append(line[:40])
        history[-1] = (line, answer)
        turns.append(
            {
                "session": session_id,
                "seed": seed,
                "turn": turn,
                "persona": persona,
                "goal": goal,
                "user_input": line,
                "assistant": answer,
                "intent": intent,
                "plan": plan,
            }
        )
        print(f"  turn {turn} [{intent}]: {line[:40]}")
        if intent == "其他" and turn > 1:
            # 目标外闲聊过多，模拟器认为聊完了
            pass
        time.sleep(0.3)
    return turns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=1)
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--username", default="e2e_b2")
    ap.add_argument("--password", default="pass123")
    ap.add_argument("--out", default="/tmp/ai_user_material.jsonl")
    args = ap.parse_args()

    llm = build_llm()
    # 登录拿 token
    r = httpx.post(
        f"{args.base_url}/api/auth/login",
        json={"username": args.username, "password": args.password},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["token"]

    all_turns = []
    for s in range(1, args.sessions + 1):
        seed = args.seed if args.seed is not None else random.randrange(1_000_000)
        all_turns.extend(run_session(s, seed, args.base_url, token, args.turns, llm))

    with open(args.out, "a", encoding="utf-8") as f:
        for t in all_turns:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"\n共 {len(all_turns)} 轮 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
