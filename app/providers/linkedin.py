"""LinkedInProfileProvider — the optional, opt-in browser-automation scraper.

DISABLED BY DEFAULT. Only used when PROVIDER=linkedin. Automating a logged-in
LinkedIn session violates LinkedIn's User Agreement and can permanently ban the
account. Use a throwaway account you are willing to lose. See README "Known
Limitations / ToS".

What is real here: the session loading, navigation, lazy-section scrolling,
"show more" expansion, error/edge-case detection, and courtesy rate limiting.
What is illustrative: the CSS selectors live in `linkedin_parsers.py` and match
the representative fixtures — against the live site they must be updated to
LinkedIn's current (obfuscated, frequently-changing) DOM.

Playwright is imported lazily so the core app/tests never require a browser.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from app.config import Settings
from app.linkedin_session import is_logged_in, new_context, storage_state_exists
from app.logging_config import get_logger
from app.providers import linkedin_parsers as parsers
from app.providers.base import (
    ProfileNotFoundError,
    ProfilePrivateError,
    RateLimitedError,
    SessionExpiredError,
    TransientProviderError,
)
from app.schemas import (
    Certification,
    Education,
    Experience,
    Language,
    Profile,
    ProfileResult,
    ProviderHealth,
    Skill,
)

logger = get_logger("provider.linkedin")


class LinkedInProfileProvider:
    name = "linkedin"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _polite_delay(self) -> None:
        lo = self._settings.fetch_min_delay_seconds
        hi = max(self._settings.fetch_max_delay_seconds, lo)
        await asyncio.sleep(random.uniform(lo, hi))

    async def healthcheck(self) -> ProviderHealth:
        # Cheap: just verify a session file exists. We do NOT launch a browser
        # or hit the network here — that would be slow and detection-prone.
        path = self._settings.session_state_path
        ok = storage_state_exists(path)
        return ProviderHealth(
            provider=self.name,
            ok=ok,
            detail=(
                f"session state present at {path}"
                if ok
                else f"no session at {path} — run `python -m scripts.login`"
            ),
        )

    async def fetch(self, url: str) -> ProfileResult:
        try:
            from playwright.async_api import async_playwright
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise TransientProviderError(
                'Playwright not installed. Run: pip install -e ".[scraper]" '
                "&& python -m playwright install chromium"
            ) from exc

        warnings: list[str] = [
            "Live LinkedIn scrape: parser selectors are illustrative and may need "
            "updating against the current DOM (see README)."
        ]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._settings.linkedin_headless)
            try:
                ctx = await new_context(browser, self._settings.session_state_path)
                page = await ctx.new_page()

                if not await is_logged_in(page):
                    raise SessionExpiredError(
                        "Not logged in — session missing/expired. Re-run scripts/login.py."
                    )

                await self._polite_delay()
                resp = await page.goto(url, wait_until="domcontentloaded")
                lowered = page.url.lower()

                if resp is not None and resp.status == 404:
                    raise ProfileNotFoundError(f"404 for {url}")
                if any(x in lowered for x in ("/authwall", "/login", "/uas/")):
                    raise SessionExpiredError("Redirected to auth wall — session invalid.")
                if "/checkpoint" in lowered:
                    raise RateLimitedError("Hit a LinkedIn checkpoint/verification page.")

                try:
                    await page.wait_for_selector("h1", timeout=15000)
                except Exception as exc:
                    raise TransientProviderError(f"Profile did not hydrate: {exc}") from exc

                await self._autoscroll(page)
                await self._expand_show_more(page)
                html = await page.content()

                profile = self._assemble(html, warnings)
                return ProfileResult(
                    url=url,
                    source=self.name,
                    scraped_at=datetime.now(timezone.utc),
                    profile=profile,
                    warnings=warnings,
                )
            except ProfilePrivateError:
                raise
            finally:
                await browser.close()

    async def _autoscroll(self, page, steps: int = 6) -> None:
        """Scroll down in increments so lazy-loaded sections hydrate."""
        for _ in range(steps):
            await page.mouse.wheel(0, 1400)
            await asyncio.sleep(random.uniform(0.4, 0.9))

    async def _expand_show_more(self, page) -> None:
        """Best-effort click of visible 'show more'/'see more' toggles."""
        selectors = [
            "button:has-text('Show more')",
            "button:has-text('see more')",
            "a:has-text('Show all')",
        ]
        for sel in selectors:
            try:
                for btn in await page.query_selector_all(sel):
                    if await btn.is_visible():
                        await btn.click(timeout=1500)
                        await asyncio.sleep(random.uniform(0.3, 0.7))
            except Exception:
                # Expansion is best-effort; never fail the scrape over it.
                continue

    def _assemble(self, html: str, warnings: list[str]) -> Profile:
        top = parsers.parse_top_card(html)
        if not top.get("name"):
            warnings.append("Could not read profile name — selectors may be stale.")
        return Profile(
            name=top.get("name"),
            headline=top.get("headline"),
            location=top.get("location"),
            about=parsers.parse_about(html),
            profile_photo_url=top.get("profile_photo_url"),
            banner_photo_url=top.get("banner_photo_url"),
            experience=[Experience(**e) for e in parsers.parse_experience(html)],
            education=[Education(**e) for e in parsers.parse_education(html)],
            skills=[Skill(**s) for s in parsers.parse_skills(html)],
            certifications=[Certification(**c) for c in parsers.parse_certifications(html)],
            languages=[Language(**lang) for lang in parsers.parse_languages(html)],
        )
