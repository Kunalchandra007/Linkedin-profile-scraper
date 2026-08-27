"""`python -m scraper.profile <url>` — matches the project brief's command.

Thin wrapper over `app.cli`, which fetches via the configured provider
(default: mock, so it runs with no credentials).
"""

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
