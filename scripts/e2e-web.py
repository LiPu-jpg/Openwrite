"""Verify relation editor: 沈烬 prefilled editable row; 伶舟 derived read-only section."""
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path("/tmp/dsh-e2e")

def open_edit(page, name):
    page.locator(f"text={name}").first.click()
    page.wait_for_timeout(1500)
    page.locator("button", has_text="编辑").first.click()
    page.wait_for_timeout(800)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto("http://127.0.0.1:3080", wait_until="networkidle")
    page.get_by_text("获取作品标题状态", exact=False).first.click()
    page.wait_for_timeout(1500)
    page.locator("button, [role=tab]", has_text="资产").first.click()
    page.wait_for_timeout(2500)

    # 伶舟: expect derived read-only section
    open_edit(page, "伶舟")
    text = page.evaluate("() => document.body.innerText")
    print("伶舟派生关系区:", "派生关系" in text, "; 只读提示:", "对方资产" in text)
    page.screenshot(path=str(OUT / "16-lingzhou-derived.png"))

    # cancel, then 沈烬: expect prefilled editable row with ling_zhou
    page.locator("button", has_text="取消").first.click()
    page.wait_for_timeout(800)
    open_edit(page, "沈烬")
    text = page.evaluate("() => document.body.innerText")
    print("沈烬预填行含 ling_zhou:", "ling_zhou" in text or "伶舟" in text)
    page.screenshot(path=str(OUT / "16b-shenjin-edit.png"))
    browser.close()
    print("done")
