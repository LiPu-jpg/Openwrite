"""Verify master-detail 资产 tab: sidebar, selection, split live preview."""
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
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "21-master-detail.png"))

    # select 伶舟 in the sidebar
    page.locator("text=伶舟").first.click()
    page.wait_for_timeout(1800)
    page.screenshot(path=str(OUT / "21b-detail.png"))

    # enter edit mode, switch body to 分栏
    page.locator("button", has_text="编辑").first.click()
    page.wait_for_timeout(800)
    split = page.locator("button, [class*=chip]", has_text="分栏").first
    split.click()
    page.wait_for_timeout(600)
    # type into the textarea and check the preview follows
    ta = page.locator("textarea").last
    ta.fill("# 沈烬\n\n- **测试**: 实时预览验证")
    page.wait_for_timeout(600)
    text = page.evaluate("() => document.body.innerText")
    print("分栏预览同步:", "实时预览验证" in text)
    page.screenshot(path=str(OUT / "21c-split.png"))
    browser.close()
    print("done")
