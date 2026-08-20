"""Verify: markdown rendering in asset detail + list fields (索引区)."""
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
    page.locator("text=伶舟").first.click()
    page.wait_for_timeout(2000)
    # markdown rendered? look for <strong>/<h2> inside the detail body instead of raw ** / ##
    rendered = page.evaluate("""() => {
      const strongs = document.querySelectorAll('strong, h1, h2, h3, blockquote').length;
      return strongs;
    }""")
    print("渲染元素数(strong/h2/blockquote):", rendered)
    text = page.evaluate("() => document.body.innerText")
    print("还残留原始 ** 标记:", "**姓名**" in text)
    print("索引区:", "索引" in text, "; 详情引用:", "详情引用" in text)
    page.screenshot(path=str(OUT / "17-markdown-detail.png"))
    browser.close()
    print("done")
