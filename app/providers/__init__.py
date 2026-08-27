"""Provider registry / factory.

`get_provider()` returns the concrete provider selected by PROVIDER. The mock and
fixture providers are imported eagerly (pure-Python, no heavy deps); the linkedin
provider is imported lazily so Playwright/bs4 are only required when it's actually
selected.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.providers.base import ProfileProvider
from app.providers.fixture import FixtureProfileProvider
from app.providers.mock import MockProfileProvider

__all__ = ["ProfileProvider", "get_provider"]


def get_provider(settings: Settings | None = None) -> ProfileProvider:
    settings = settings or get_settings()
    name = (settings.provider or "mock").lower()

    if name == "mock":
        return MockProfileProvider()
    if name == "fixture":
        return FixtureProfileProvider()
    if name == "linkedin":
        from app.providers.linkedin import LinkedInProfileProvider  # lazy: heavy deps

        return LinkedInProfileProvider(settings)

    raise ValueError(
        f"Unknown PROVIDER={settings.provider!r} (expected one of: mock, fixture, linkedin)"
    )
