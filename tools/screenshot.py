"""Render a URL with Playwright, report console/JS errors and save a screenshot.

    python tools/screenshot.py [url] [output.png] [--full] [--width 1440]
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "http://127.0.0.1:8000"
out = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else Path("shot.png")
full = "--full" in sys.argv
width = 1440
if "--width" in sys.argv:
    width = int(sys.argv[sys.argv.index("--width") + 1])

errors: list[str] = []
failed: list[str] = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: failed.append(f"{r.url} -> {r.failure}"))
    response = page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1200)
    if full:
        # Walk the page so scroll-triggered reveals settle before capturing.
        height = page.evaluate("document.body.scrollHeight")
        for offset in range(0, height, 700):
            page.evaluate(f"window.scrollTo(0, {offset})")
            page.wait_for_timeout(120)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
    page.screenshot(path=str(out), full_page=full)
    title = page.title()
    h1 = page.inner_text("h1") if page.query_selector("h1") else "(no h1)"
    browser.close()

print(f"status   : {response.status if response else 'n/a'}")
print(f"title    : {title}")
print(f"h1       : {h1.replace(chr(10), ' / ')}")
print(f"saved    : {out.resolve()}")
print(f"console  : {errors if errors else 'clean'}")
print(f"failed   : {failed if failed else 'none'}")
