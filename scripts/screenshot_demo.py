"""无头浏览器演示截图（作业 8.1 提交材料：演示截图）

跑法：uv run python scripts/screenshot_demo.py（需 webapp 已启动）
产出：docs/screenshots/ 下 5 张演示截图
"""
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:8000"


def wait_reply(page, timeout_ms=60000):
    """等待最后一次 AI 气泡不再打字（.typing 移除）且非空"""
    last = page.locator(".msg.ai .bubble").last
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        cls = last.get_attribute("class") or ""
        text = (last.inner_text() or "").strip()
        if "typing" not in cls and text:
            return text
        time.sleep(0.3)
    return last.inner_text()


def main() -> None:
    chrome = os.path.expanduser(
        "~/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome)
        page = browser.new_page(viewport={"width": 1000, "height": 760})
        page.goto(BASE)
        page.wait_for_selector(".chips .chip")
        time.sleep(0.6)
        page.screenshot(path=str(OUT / "01-首页.png"))

        script = [
            ("帮我规划10月8日去北京开会4天的行程", "02-行程规划.png"),
            ("北京今天天气怎么样", "03-联网天气.png"),
            ("那上海呢", "04-指代消解.png"),
            ("出差住宿标准是什么", "05-知识问答.png"),
            ("我上次的行程是什么", "06-历史查询.png"),
        ]
        for i, (text, fname) in enumerate(script):
            page.fill("#input", text)
            page.click("#send")
            wait_reply(page)
            page.screenshot(path=str(OUT / fname))
            print(f"  ✓ {fname}（第 {i + 1} 条回复完成）")
        browser.close()


if __name__ == "__main__":
    main()
    print(f"完成：{OUT}")
