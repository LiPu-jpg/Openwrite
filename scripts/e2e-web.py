"""Re-verify: card summary size + detail field alignment."""
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
    page.screenshot(path=str(OUT / "20-cards-fixed.png"))
    # summary font size should be much smaller than the card name
    sizes = page.evaluate("""() => {
      const card = document.querySelector('text=伶舟') ? null : null;
      const name = Array.from(document.querySelectorAll('*')).find(e => e.textContent === '伶舟' && e.children.length === 0);
      if (!name) return null;
      const cardEl = name.closest('li, article, div');
      const summary = Array.from(cardEl.querySelectorAll('*')).find(e => e.textContent.includes('姓名') && e.children.length <= 2);
      return { name: getComputedStyle(name).fontSize, summary: summary ? getComputedStyle(summary).fontSize : null };
    }""")
    print("字号:", sizes)
    page.locator("text=伶舟").first.click()
    page.wait_for_timeout(1800)
    page.screenshot(path=str(OUT / "20b-detail-fixed.png"))
    browser.close()
    print("done")
