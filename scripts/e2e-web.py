"""Verify body editor preview toggle on 沈烬 (read-only check, no save)."""
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path("/tmp/dsh-e2e")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto("http://127.0.0.1:3080", wait_until="networkidle")
    page.get_by_text("获取作品标题状态", exact=False).first.click()
    page.wait_for_timeout(1500)
    page.locator("button, [role=tab]", has_text="资产").first.click()
    page.wait_for_timeout(2500)
    # 沈烬 card — click its name heading
    page.locator("text=沈烬").first.click()
    page.wait_for_timeout(1800)
    page.locator("button", has_text="编辑").first.click()
    page.wait_for_timeout(800)
    text = page.evaluate("() => document.body.innerText")
    print("正文区存在:", "正文" in text, "; 预览切换:", "预览" in text)
    # switch to preview
    prev = page.locator("button, [class*=chip]", has_text="预览").first
    prev.click()
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "19-body-preview.png"))
    print("shot ok")
    browser.close()
    print("done")
