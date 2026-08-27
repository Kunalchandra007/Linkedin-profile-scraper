"""Log into LinkedIn with a *headed* browser and save the authenticated session.

    python -m scripts.login

Reads LI_EMAIL / LI_PASSWORD from .env, then opens a visible browser so you can
complete any 2FA / security checkpoint by hand. Once you confirm you're logged in,
it saves cookies + localStorage to SESSION_STATE_PATH (gitignored). The scraper
reuses this state and never logs in per request.

Run again whenever the session expires (the scraper will fail loudly with a
SessionExpiredError telling you to do so).

⚠️  Automating a logged-in LinkedIn session violates LinkedIn's User Agreement and
    can get the account permanently banned. Use a THROWAWAY account you are willing
    to lose — never your personal one. See the README's "Known Limitations / ToS".
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import get_settings
from app.linkedin_session import LOGIN_URL, is_logged_in


async def main() -> int:
    settings = get_settings()
    if not settings.li_email or not settings.li_password:
        print("✋ Set LI_EMAIL and LI_PASSWORD in your .env first.")
        return 2

    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError:
        print(
            'Playwright is not installed. Run:\n'
            '  pip install -e ".[scraper]"\n'
            "  python -m playwright install chromium"
        )
        return 2

    session_path = settings.session_state_path
    Path(session_path).parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        try:
            await page.fill("#username", settings.li_email)
            await page.fill("#password", settings.li_password)
            await page.click("button[type=submit]")
        except Exception as exc:
            print(f"(Could not auto-fill the login form: {exc}. Log in manually in the window.)")

        print(
            "\nA browser window is open. Complete login and any 2FA / checkpoint there.\n"
            "When you can see your LinkedIn feed, come back here and press ENTER.\n"
        )
        # Intentional blocking prompt — this script is run interactively by a human.
        input("Press ENTER once you are fully logged in... ")

        if await is_logged_in(page):
            await context.storage_state(path=session_path)
            print(f"✅ Session saved to {session_path}")
            code = 0
        else:
            print("❌ Does not look logged in — not saving. Re-run and try again.")
            code = 1

        await browser.close()
        return code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
