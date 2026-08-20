"""E2E: redesigned 资产 tab — segments, subcategory groups, card expansion."""
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
    page.locator("button, [role=tab]", has_text="资产").first.click()
    page.wait_for_timeout(3000)
    page.screenshot(path=str(OUT / "13-assets-main.png"))

    # 设定 segment
    seg = page.locator("button", has_text="设定")
    if seg.count() > 0:
        seg.first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "13b-assets-world.png"))
        print("segment 设定 ok")

    # expand the first card (角色 segment or wherever we are)
    page.locator("button", has_text="角色").first.click()
    page.wait_for_timeout(1200)
    card = page.locator("[class*=card], [class*=Card], li, article").first
    try:
        page.locator("text=伶舟").first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "13c-assets-detail.png"))
        print("detail expand ok")
    except Exception as e:
        print("detail expand failed:", type(e).__name__)

    # 作品核心 segment
    core = page.locator("button", has_text="作品核心")
    if core.count() > 0:
        core.first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "13d-assets-core.png"))
        print("segment 作品核心 ok")
    browser.close()
    print("done")
