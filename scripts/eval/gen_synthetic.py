#!/usr/bin/env python3
"""LLM 合成样本生成器（思路 2：从种子扩变体，覆盖维度 4/5 边界与格式语气）。

种子：intent_golden.jsonl 每意图 1-2 条。变体方向：口语化 / 方言 / 英文混 /
情绪化 / 极简 / 冗余 / 指代 / 擦边能力外。变体保留种子意图（expected 继承）。

产物：tests/data/synthetic_golden.jsonl + 人工抽检清单（stdout，需人工过目后
才可视为有效样本——LLM 生成可能漂移，spec「测试自洽」原则下不自动进黄金集）。

用法：uv run python scripts/eval/gen_synthetic.py [--seed-n 每意图种子数] [--per-seed 每种子变体数]
"""

import argparse
import json
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from xiao_wen.llm import get_llm

ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN = ROOT / "tests" / "data" / "intent_golden.jsonl"
OUT = ROOT / "tests" / "data" / "synthetic_golden.jsonl"

# 变体方向 = 维度 4/5 的边界 + 格式语气采样
VARIANTS = [
    "口语化：加语气词、缩短句子（如「帮我搞个10月20号去广州出差的行程呗」）",
    "方言/地域腔：用北方或南方口语（如「俺10月20号要去广州出差4天」）",
    "中英混：夹英文单词（如「10月20号 plan 个去广州出差 4 天的 trip」）",
    "情绪化：带烦躁或急切语气（如「怎么又要出差！！10月20号广州4天赶紧的！」）",
    "极简：只给必要要素（如「去广州4天」）",
    "冗余：大量铺垫后才说正事（如「那个……我想麻烦你一下，就是能不能帮我规划一下…」）",
    "指代：用「和上次一样」「老地方」等指代（保持请求意图可识别）",
    "擦边能力外：要工具能力（如「帮我订10月20日去广州的机票」）——意图应判「其他」或原意图",
]

_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是评测样本生成器。给定一条种子用户请求（含其意图标签），按指定变异方向"
            "生成 1 条语义等价但表达不同的新请求。只输出 JSON 对象："
            '{{"input": "新请求文本"}}，不要多余内容。',
        ),
        (
            "human",
            "种子请求：{seed}\n意图：{intent}\n变异方向：{variant}\n\n输出：",
        ),
    ]
)


class _Output(dict):
    pass


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 合成样本生成器")
    ap.add_argument("--seed-n", type=int, default=1, help="每意图种子数")
    ap.add_argument("--per-seed", type=int, default=8, help="每种子变体数（<= 变异方向数）")
    args = ap.parse_args()

    lines = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    by_intent: dict[str, list[dict]] = {}
    for line in lines:
        by_intent.setdefault(line["expected"], []).append(line)
    seeds = [v[0] for v in by_intent.values()][:6]  # 前 6 意图各 1 条种子

    llm = get_llm().with_structured_output(_Output, method="json_mode")
    samples: list[dict] = []
    for si, seed in enumerate(seeds, 1):
        for vi, variant in enumerate(VARIANTS[: args.per_seed]):
            try:
                out = llm.invoke(_PROMPT.format_messages(seed=seed["input"], intent=seed["expected"], variant=variant))
                text = str(out.get("input", "")).strip()
            except Exception as e:
                print(f"  [{si}.{vi + 1}] 生成失败: {e}", file=__import__("sys").stderr)
                continue
            if not text:
                continue
            samples.append(
                {"input": text, "expected": seed["expected"], "note": f"合成:{variant.split('：')[0]}"}
            )
            print(f"[{si}.{vi + 1}] {seed['expected']} | {text[:46]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in samples) + "\n", encoding="utf-8")
    print(f"\n合成样本 {len(samples)} 条 → {OUT}")
    print("⚠️ 需人工抽检后再视为有效（LLM 生成可能漂移意图）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
