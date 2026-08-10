"""第十四课（演示）：插件化、模块化架构 —— 加分项 C

动态发现（目录扫描 + 元数据） / 懒加载（用到才执行） / 渐进式披露（AST 只读元数据）
主管与插件完全解耦：新增插件不修改主管任何代码。

跑法：python homework/0012_plugin.py
四幕演示：
  第1幕 动态发现：扫描 plugins/，只读元数据，不执行任何插件代码
  第2幕 懒加载：触发意图才 exec_module（哨兵日志为证）
  第3幕 热插拔：运行中新增插件 → 重新发现 → 主管自动认识新意图
  第4幕 边界兜底：「其他」
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from plugin_registry import discover, load_plugin

load_dotenv()

# 主管自己的 LLM 配置（不预加载任何 worker/插件）
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)


class Intent(BaseModel):
    intent: str   # 动态类别：运行时从 manifest 校验（插件化的固有权衡：静态类型变弱）
    reason: str


def build_prompt(manifest: list[dict]) -> ChatPromptTemplate:
    """意图识别提示词 = manifest 自动生成 → 加插件自动多一类意图，主管零改动"""
    descs = "\n".join(f"- {p['INTENT']}：{p['DESCRIPTION']}" for p in manifest)
    return ChatPromptTemplate.from_messages([
        ("system", f"""你是插件式差旅助手的主管。可路由的意图类别（由插件动态注册）：\n{descs}\n
规则：判断用户输入最匹配的意图类别；无法匹配输出「其他」（个人休闲/非差旅一律「其他」）。
输出严格 JSON，键名：intent（上述类别之一）、reason（一句话理由）。"""),
        ("human", "用户输入：{input}"),
    ])


def supervisor(text: str, manifest: list[dict]) -> str:
    """主管：识别意图 → 运行时校验（动态类别无法静态类型化）→ 懒加载插件 → 派发"""
    model = build_prompt(manifest) | llm.with_structured_output(Intent, method="json_mode")
    r = model.invoke({"input": text})
    assert isinstance(r, Intent)  # json_mode 结构化输出返回模型实例
    known = {p["INTENT"] for p in manifest}
    if r.intent not in known:
        r.intent = "其他"
    if r.intent == "其他":
        return ("抱歉，这不在企业差旅助手的服务范围内（当前由插件注册的意图："
                + "、".join(known) + "）。")
    mod = load_plugin(r.intent)
    assert hasattr(mod, "run")
    return mod.run(text)


if __name__ == "__main__":
    PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"

    print("=" * 60)
    print("第1幕｜动态发现（渐进式披露）：只读元数据，不执行插件代码")
    manifest = discover()
    for p in manifest:
        print(f"  🔍 {p['file']:<14} → {p['INTENT']}：{p['DESCRIPTION']}")
    print(f"  → 意图类别：{'、'.join(p['INTENT'] for p in manifest)} + 其他（兜底）")
    print("  → 无任何『模块已执行』日志 = AST 渐进披露生效，意图识别阶段零加载\n")

    print("=" * 60)
    print("第2幕｜懒加载：触发意图才 exec_module（看哨兵日志）")
    for q in ["出差住宿标准是什么", "北京今天天气怎么样"]:
        print(f"  用户：{q}")
        ans = supervisor(q, manifest)
        print(f"  答复：{ans[:80]}…" if len(ans) > 80 else f"  答复：{ans}")
        print()

    print("=" * 60)
    print("第3幕｜热插拔：运行中新增插件 → 重新发现 → 主管自动认识新意图")
    new_plugin = '''"""插件：差旅总结（运行中热插拔加入）"""
print("  ⚠️ [summary] 模块已执行（懒加载触发）")

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "homework"))
from memory_store import get_itineraries, get_preferences

INTENT = "差旅总结"
DESCRIPTION = "汇总差旅次数、常用目的地、已知偏好习惯"

def run(query: str) -> str:
    its = get_itineraries()
    prefs = get_preferences()
    pref_txt = "；".join(f"{p['category']}:{p['content']}" for p in prefs) or "无"
    n = len(its)
    dests = {i.get("to_city") for i in its if i.get("to_city") not in ("待定", "未知")}
    return f"🧳 差旅档案：共 {n} 次行程，去过 {'、'.join(sorted(dests)) or '暂无'}；偏好：{pref_txt}"
'''
    (PLUGIN_DIR / "summary.py").write_text(new_plugin, encoding="utf-8")
    manifest = discover()
    print(f"  → 重新发现，现在 {len(manifest)} 个插件："
          f"{'、'.join(p['INTENT'] for p in manifest)}")
    q = "帮我总结一下我的差旅情况"
    print(f"  用户：{q}")
    print(f"  答复：{supervisor(q, manifest)}\n")

    print("=" * 60)
    print("第4幕｜边界兜底")
    q = "这个暑假去哪里玩"
    print(f"  用户：{q}")
    print(f"  答复：{supervisor(q, discover())}\n")

    # 清理热插拔演示文件（保持插件目录为课程基线三件套）
    (PLUGIN_DIR / "summary.py").unlink()
    print("（已清理热插拔演示文件 summary.py，插件目录恢复基线）")
