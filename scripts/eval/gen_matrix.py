#!/usr/bin/env python3
"""要素矩阵生成器：穷举 5 要素 × 3 态（明确/缺失/模糊）= 243 组合的行程请求样本。

思路（Hypothesis 式组合穷举）：行程场景的输入空间 = 五要素（出发/目的/日期/天数/
住宿偏好）的取值组合。每要素三态：present（明确值）/ absent（缺失）/
vague（模糊值）。全组合生成即铺开「维度 2 要素完整度」的全部边界。

产物：tests/data/matrix_golden.jsonl（每行 {input, expected, missing, vague, note}）
- expected 恒为「行程规划」（模板只产行程请求）
- missing = 缺失要素名列表（结构层验证缺项追问的预期依据）
- vague = 模糊要素名列表（意图识别稳定性素材）

用法：uv run python scripts/eval/gen_matrix.py [--out tests/data/matrix_golden.jsonl]
"""

import argparse
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# 要素三态短语表：absent 用空串（该要素不出现）
# 必填四要素（缺项检查只盯它们）：出发/目的城市、日期、天数；住宿偏好为可选（缺了不追问）
ELEMENTS: dict[str, dict[str, str]] = {
    "出发城市": {"present": "从上海出发", "vague": "从家里出发", "absent": ""},
    "目的城市": {"present": "去广州", "vague": "去南方", "absent": ""},
    "日期": {"present": "10月20日", "vague": "下周", "absent": ""},
    "天数": {"present": "出差4天", "vague": "出差几天", "absent": ""},
    "住宿偏好": {"present": "住全季酒店", "vague": "住经济一点的酒店", "absent": ""},
}
REQUIRED = ("出发城市", "目的城市", "日期", "天数")
STATES = ("present", "vague", "absent")


def generate() -> list[dict]:
    """全组合：5 要素 × 3 态 = 243 条。missing 只统计必填四要素（住宿偏好可选）。"""
    names = list(ELEMENTS)
    samples: list[dict] = []
    for combo in itertools.product(STATES, repeat=len(names)):
        phrases, missing, vague = [], [], []
        for name, state in zip(names, combo, strict=False):
            if state == "absent":
                if name in REQUIRED:
                    missing.append(name)
            elif state == "vague":
                vague.append(name)
            phrases.append(ELEMENTS[name][state])
        body = " ".join(p for p in phrases if p)
        text = f"帮我规划{body}的行程".replace("  ", " ")
        samples.append(
            {
                "input": text,
                "expected": "行程规划",
                "missing": missing,
                "vague": vague,
                "note": "矩阵"
                + (f" 缺失:{'/'.join(missing)}" if missing else "")
                + (f" 模糊:{'/'.join(vague)}" if vague else "")
                + (" 全要素" if not missing and not vague else ""),
            }
        )
    return samples


def main() -> int:
    ap = argparse.ArgumentParser(description="要素矩阵样本生成器（243 组合）")
    ap.add_argument("--out", default=ROOT / "tests" / "data" / "matrix_golden.jsonl", type=Path)
    args = ap.parse_args()

    samples = generate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in samples) + "\n", encoding="utf-8")
    print(f"矩阵样本 {len(samples)} 条 → {args.out}")
    full = sum(1 for s in samples if not s["missing"] and not s["vague"])
    print(f"全要素 {full} | 含缺失 {len(samples) - full}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
