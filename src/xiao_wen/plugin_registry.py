"""子 Agent 注册中心：动态发现 + 渐进式披露 + 懒加载（多 Agent 架构的核心机制）

- 动态发现：discover() 扫描内置子 Agent 目录（src/xiao_wen/agents/）+ 外部扩展目录
  （plugins/），加文件即自动注册——多 Agent 主管通过注册表认识全部子 Agent
- 渐进式披露：read_metadata() 用 AST 只读模块顶部的 INTENT/DESCRIPTION 元数据，
  不执行子 Agent 代码（意图识别阶段零加载，只取「有哪些意图可用」）
- 懒加载：load_agent() 真正派发时才加载（内置 import_module / 外部 exec_module），
  _loaded 缓存防重复加载（未使用的子 Agent 不加载）
- 优先级：内置子 Agent 优先；外部扩展仅在意图不与内置冲突时并入
"""
import ast
import importlib
import importlib.util
from pathlib import Path
from typing import Protocol

from xiao_wen import ROOT

AGENT_DIR = ROOT / "src" / "xiao_wen" / "agents"  # 内置子 Agent 目录（包内，import_module 加载）
PLUGIN_DIR = ROOT / "plugins"                     # 外部扩展目录（文件路径 exec_module 加载）

_loaded: dict[str, object] = {}


class AgentModule(Protocol):
    """子 Agent 实体契约：INTENT/DESCRIPTION 元数据 + 统一 run(state) -> dict 接口"""
    INTENT: str
    DESCRIPTION: str
    def run(self, state: dict) -> dict: ...


def read_metadata(path: Path) -> dict[str, str]:
    """AST 静态解析模块顶部的 INTENT/DESCRIPTION 赋值，不执行模块代码"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    meta: dict[str, str] = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("INTENT", "DESCRIPTION")):
            try:
                val = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(val, str):
                meta[node.targets[0].id] = val
    return meta


def _scan(directory: Path, source: str) -> list[dict]:
    """单目录扫描：返回 [{file, INTENT, DESCRIPTION, source}]，全程零加载"""
    found: list[dict] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        meta = read_metadata(path)
        if "INTENT" in meta and "DESCRIPTION" in meta:
            found.append({"file": path.name, "source": source, **meta})
    return found


def discover() -> list[dict]:
    """自动扫描注册：内置子 Agent 优先，外部扩展同意图时并入；全程零加载"""
    agents = _scan(AGENT_DIR, "builtin")
    owned = {m["INTENT"] for m in agents}
    for m in _scan(PLUGIN_DIR, "external"):
        if m["INTENT"] not in owned:  # 内置优先：同名意图外部扩展被忽略
            agents.append(m)
    return agents


def load_agent(intent: str) -> AgentModule:
    """懒加载：派发到该意图时才真正加载子 Agent 模块（含它的全部 import）"""
    if intent in _loaded:
        return _loaded[intent]  # type: ignore[return-value]
    for m in discover():
        if m["INTENT"] != intent:
            continue
        if m["source"] == "builtin":
            mod = importlib.import_module(f"xiao_wen.agents.{m['file'][:-3]}")
        else:
            spec = importlib.util.spec_from_file_location(
                m["file"][:-3], PLUGIN_DIR / m["file"])
            if spec is None or spec.loader is None:
                raise ImportError(f"子 Agent 加载失败：{m['file']}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        _loaded[intent] = mod
        return mod  # type: ignore[return-value]
    raise KeyError(f"未知子 Agent 意图：{intent}")


# 兼容别名：旧接口名（插件 → 子 Agent 语义升级）
def load_plugin(intent: str) -> object:
    return load_agent(intent)
