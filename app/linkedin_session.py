"""Reusable LinkedIn session helpers, shared by the login script and the scraper.

Centralizing this means scraping code never logs in per-request — it always loads
the storage state produced once by `scripts/login.py`. `is_logged_in` lets callers
fail loudly on an expired session instead of silently scraping a logged-out page.

Playwright is imported lazily by callers; this module only needs its page/browser
objects duck-typed, so it has no hard Playwright import itself.
"""

from __future__ import annotations

from pathlib import Path

FEED_URL = "https://www.linkedin.com/feed/"
LOGIN_URL = "https://www.linkedin.com/login"

# A realistic desktop UA reduces trivially-obvious automation signals. This is
# not an anti-detection measure and does not make automated access compliant.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def storage_state_exists(path: str) -> bool:
    return Path(path).is_file()


async def new_context(browser, storage_state_path: str | None):
    """Create a browser context, loading saved auth state if present."""
    kwargs: dict = {
        "user_agent": DEFAULT_USER_AGENT,
        "viewport": {"width": 1280, "height": 900},
        "locale": "en-US",
    }
    if storage_state_path and storage_state_exists(storage_state_path):
        kwargs["storage_state"] = storage_state_path
    return await browser.new_context(**kwargs)


async def is_logged_in(page) -> bool:
    """Return True iff navigating to the feed renders as an authenticated user."""
    await page.goto(FEED_URL, wait_until="domcontentloaded")
    lowered = page.url.lower()
    if any(x in lowered for x in ("/login", "/authwall", "/checkpoint", "/uas/")):
        return False
    try:
        await page.wait_for_selector("nav", timeout=8000)
    except Exception:
        return False
    return "linkedin.com/feed" in page.url.lower()
