"""Quick check: composer overlap fix — scroll 大纲 view to bottom and screenshot."""
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path("/tmp/dsh-e2e")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto("http://127.0.0.1:3080", wait_until="networkidle")
    page.get_by_text("获取作品标题状态", exact=False).first.click()
    page.wait_for_timeout(1500)
    page.locator("button, [role=tab]", has_text="大纲").first.click()
    page.wait_for_timeout(2500)
    page.evaluate("""() => {
      const els = Array.from(document.querySelectorAll('div')).filter(el => el.scrollHeight > el.clientHeight + 50);
      const scroller = els.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
      if (scroller) scroller.scrollTop = scroller.scrollHeight;
    }""")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "06-outline-bottom.png"))
    print("shot: 06-outline-bottom.png")
    browser.close()
