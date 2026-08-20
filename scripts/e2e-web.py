"""Re-verify 图谱 tab: 伏笔 empty state text + filtered 关系图."""
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path("/tmp/dsh-e2e")
OUT.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto("http://127.0.0.1:3080", wait_until="networkidle")
    page.get_by_text("获取作品标题状态", exact=False).first.click()
    page.wait_for_timeout(1500)
    page.locator("button, [role=tab]", has_text="图谱").first.click()
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "12-graph-empty.png"))
    text = page.evaluate("() => document.body.innerText")
    print("伏笔空态文案:", "暂无待回收伏笔" in text)

    page.get_by_text("关系图", exact=False).first.click()
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "12-graph-rel-filtered.png"))
    print("done")
    browser.close()
