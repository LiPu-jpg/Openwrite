"""E2E: Goethe preset session + skill loading — with failure diagnostics."""
import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path("/tmp/dsh-e2e")
OUT.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    try:
        page.goto("http://127.0.0.1:3080", wait_until="networkidle")

        preset_btn = page.locator("button", has_text="模式").or_(
            page.locator("button", has_text="写作")).or_(
            page.locator("button", has_text="规划"))
        if preset_btn.count() == 0:
            page.locator("button", has_text="新会话").first.click()
            page.wait_for_timeout(1000)
        preset_btn.first.click()
        page.wait_for_timeout(500)
        page.get_by_text("Goethe 规划", exact=True).click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "07a-goethe-preset.png"))

        box = page.locator("textarea").first
        box.fill("用 skill 工具加载 oh-story-long-scan 技能，然后用一句话告诉我它的用途。不要调用其他工具。")
        box.press("Enter")
        page.get_by_text("扫描", exact=False).first.wait_for(timeout=120000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "07-goethe-skill.png"))
        print("shot: 07-goethe-skill.png")
    except Exception as e:
        page.screenshot(path=str(OUT / "07-failure.png"))
        text = page.evaluate("() => document.body.innerText.slice(0, 3000)")
        (OUT / "07-failure.txt").write_text(text)
        print(f"FAILED: {type(e).__name__}; page state dumped")
    finally:
        browser.close()
    print("done")
