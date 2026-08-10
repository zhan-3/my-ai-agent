"""插件注册中心：动态发现 + 渐进式披露 + 懒加载（加分项 C 核心机制）

- 动态发现：discover() 扫描 plugins/ 目录，加插件文件即自动注册
- 渐进式披露：read_metadata() 用 AST 只读插件顶部的 INTENT/DESCRIPTION 元数据，
  不执行插件代码（意图识别阶段零加载）
- 懒加载：load_plugin() 真正派发时才 exec_module，_loaded 缓存防重复加载
"""
import ast
import importlib.util
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"

_loaded: dict[str, object] = {}


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


def discover() -> list[dict]:
    """自动扫描注册：返回 [{file, INTENT, DESCRIPTION}]，全程零加载"""
    plugins: list[dict] = []
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        meta = read_metadata(path)
        if "INTENT" in meta and "DESCRIPTION" in meta:
            plugins.append({"file": path.name, **meta})
    return plugins


def load_plugin(intent: str) -> object:
    """懒加载：派发到该意图时才真正执行插件模块（含它的全部 import）"""
    for p in discover():
        if p["INTENT"] == intent:
            if intent not in _loaded:
                spec = importlib.util.spec_from_file_location(
                    p["file"][:-3], PLUGIN_DIR / p["file"])
                if spec is None or spec.loader is None:
                    raise ImportError(f"插件加载失败：{p['file']}")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _loaded[intent] = mod
            return _loaded[intent]
    raise KeyError(f"未知插件意图：{intent}")
