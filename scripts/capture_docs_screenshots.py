"""Capture non-sensitive UI screenshots from an isolated deployment."""

from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUT = Path("/app/data/docs-upgrade-screenshots")
OUTPUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.goto("http://frontend/", wait_until="networkidle")
    page.screenshot(path=str(OUTPUT / "collection-synthetic.png"))
    for label, filename in [
        ("知识库", "library-synthetic.png"),
        ("搜索", "search-synthetic.png"),
        ("问答", "ask-synthetic.png"),
        ("笔记", "notes-synthetic.png"),
        ("设置", "settings-synthetic.png"),
    ]:
        page.get_by_role("button", name=label, exact=True).click()
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUTPUT / filename))
        if label == "设置":
            page.get_by_role("button", name="AI 模型", exact=True).click()
            page.wait_for_timeout(250)
            page.screenshot(path=str(OUTPUT / "settings-models-synthetic.png"))
    browser.close()

print(f"captured={len(list(OUTPUT.glob('*.png')))} directory={OUTPUT}")
