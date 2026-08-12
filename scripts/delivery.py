"""交付门禁 + 打包 + 解包自检

用法（在项目根，venv 已激活）：
  python scripts/delivery.py gate      # 全量门禁：pytest + mypy + 冒烟
  python scripts/delivery.py package   # 门禁 → 打包 → 解包自检（产出 delivery/*.zip）
  python scripts/delivery.py all       # 全流程（推荐，约 4 分钟）

设计要点：
- 门禁 = 本地 CI：任一步失败即退出，禁止打包
- 打包 = 白名单（漏掉好过泄密：.env/.venv/data 天然不进包）
- 自检 = 解到临时目录重跑离线门禁，证明压缩包自洽（不依赖本机状态）
"""
import datetime
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 打包白名单（最终成品）：显式列出
# .env/.venv/data/AGENTS.md/.scratch 天然排除
WHITELIST = [
    "README.md", "pyproject.toml", "uv.lock",
    "src", "tests", "plugins", "scripts", "docs",
]
SKIP_PART = {"__pycache__", ".pytest_cache", ".mypy_cache", ".venv"}


def _run(cmd: list[str], cwd: Path, label: str) -> None:
    print(f"▶ {label}\n  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        print(f"✗ {label} 失败（退出码 {r.returncode}）")
        raise SystemExit(1)
    print(f"✓ {label}")


def gate() -> None:
    """全量门禁：单元 + 集成 + 类型检查 + 冒烟（需要 .env 与网络）"""
    _run([PY, "-m", "pytest", "-q", "-m", "not integration"], ROOT, "单元测试（无 LLM）")
    _run([PY, "-m", "pytest", "-q", "-m", "integration"], ROOT, "集成测试（真实 LLM）")
    _run([PY, "-m", "mypy"], ROOT, "类型检查（mypy）")
    _run([PY, "scripts/smoke.py"], ROOT, "演示冒烟（真 LLM）")


def _collect() -> list[Path]:
    files: list[Path] = []
    for name in WHITELIST:
        p = ROOT / name
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(part in SKIP_PART for part in f.parts):
                    files.append(f)
        else:
            print(f"⚠ 白名单项不存在：{name}")
    return files


def package() -> None:
    gate()  # 门禁不过不打包
    out_dir = ROOT / "delivery"
    out_dir.mkdir(exist_ok=True)
    name = f"xiao-wen-assistant-{datetime.date.today().isoformat()}.zip"
    zip_path = out_dir / name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _collect():
            z.write(f, f.relative_to(ROOT))
    print(f"\n✓ 打包完成：{zip_path}（{len(_collect())} 个文件）")

    # 解包自检：临时目录重跑离线门禁（无 .env/数据，验「代码+配置自洽」）
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(td_path)
        print(f"\n▶ 解包自检（{td_path}）")
        _run([PY, "-m", "pytest", "-q", "-m", "not integration"], td_path, "自检：单元测试")
        _run([PY, "-m", "mypy"], td_path, "自检：类型检查")
        _run([PY, "scripts/smoke.py", "--import-only"], td_path, "自检：模块可加载")
    print("\n✓ 自检通过——压缩包自洽，可以提交")


    if (ROOT / "delivery").is_dir():
        zips = sorted((ROOT / "delivery").glob("*.zip"))
        if zips:
            print("当前压缩包：")
            for z in zips:
                print(f"  {z.name}（{z.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "gate":
        gate()
    elif cmd == "package":
        package()
    elif cmd == "all":
        gate()
        package()
    else:
        print(f"未知命令：{cmd}（可用：gate / package / all）")
        sys.exit(2)
