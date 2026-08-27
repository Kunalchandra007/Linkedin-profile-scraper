"""Pure HTML → dict parsers for LinkedIn profile sections.

These functions contain *no* browser or network code — they take an HTML string
and return plain dicts/lists shaped like `app.schemas`. That separation is what
makes the scraping logic unit-testable against saved HTML fixtures in CI, with no
live LinkedIn access (see tests/test_parsers.py and tests/fixtures/html/).

The selectors here are illustrative and match the representative fixtures. Real
LinkedIn markup is obfuscated and changes often; adapting these selectors to the
live DOM is expected maintenance (documented in the README's Known Limitations).
"""

from __future__ import annotations

import re

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError as exc:  # pragma: no cover - only when extra not installed
    raise ModuleNotFoundError(
        "HTML parsing needs beautifulsoup4. Install the scraper/dev extra: "
        'pip install -e ".[scraper]"  (or ".[dev]")'
    ) from exc


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def _text(node) -> str | None:
    return _clean(node.get_text()) if node else None


def _parse_date_range(text: str | None) -> tuple[str | None, str | None, bool]:
    """'Jan 2021 - Present · 3 yrs' -> ('Jan 2021', None, True)."""
    if not text:
        return (None, None, False)
    main = text.split("·")[0].strip()
    parts = [p.strip() for p in re.split(r"[-–—]", main, maxsplit=1)]
    if len(parts) == 1:
        return (parts[0] or None, None, False)
    start, end_raw = parts[0] or None, parts[1]
    if end_raw.lower() in {"present", "now"}:
        return (start, None, True)
    return (start, end_raw or None, False)


def _split_on_dot(text: str | None) -> tuple[str | None, str | None]:
    """'Acme · Full-time' -> ('Acme', 'Full-time')."""
    if not text:
        return (None, None)
    parts = [p.strip() for p in text.split("·", 1)]
    return (parts[0] or None, parts[1] if len(parts) > 1 and parts[1] else None)


def parse_top_card(html: str) -> dict:
    soup = _soup(html)
    photo = soup.select_one("img.profile-photo")
    banner = soup.select_one("img.profile-banner")
    return {
        "name": _text(soup.select_one(".profile-name")),
        "headline": _text(soup.select_one(".profile-headline")),
        "location": _text(soup.select_one(".profile-location")),
        "profile_photo_url": photo.get("src") if photo else None,
        "banner_photo_url": banner.get("src") if banner else None,
    }


def parse_about(html: str) -> str | None:
    soup = _soup(html)
    return _text(soup.select_one("section.about"))


def parse_experience(html: str) -> list[dict]:
    soup = _soup(html)
    out: list[dict] = []
    for li in soup.select("#experience .experience-item"):
        company, emp_type = _split_on_dot(_text(li.select_one(".exp-company")))
        start, end, current = _parse_date_range(_text(li.select_one(".exp-daterange")))
        out.append(
            {
                "title": _text(li.select_one(".exp-title")),
                "company": company,
                "employment_type": emp_type,
                "location": _text(li.select_one(".exp-location")),
                "start_date": start,
                "end_date": end,
                "is_current": current,
                "description": _text(li.select_one(".exp-description")),
            }
        )
    return out


def parse_education(html: str) -> list[dict]:
    soup = _soup(html)
    out: list[dict] = []
    for li in soup.select("#education .edu-item"):
        degree_field = _text(li.select_one(".edu-degree"))
        degree, field = (None, None)
        if degree_field:
            bits = [b.strip() for b in degree_field.split(",", 1)]
            degree = bits[0] or None
            field = bits[1] if len(bits) > 1 else None
        start, end, _ = _parse_date_range(_text(li.select_one(".edu-daterange")))
        out.append(
            {
                "school": _text(li.select_one(".edu-school")),
                "degree": degree,
                "field_of_study": field,
                "start_date": start,
                "end_date": end,
                "description": _text(li.select_one(".edu-description")),
            }
        )
    return out


def parse_skills(html: str) -> list[dict]:
    soup = _soup(html)
    out: list[dict] = []
    for li in soup.select("#skills .skill-item"):
        name = _text(li.select_one(".skill-name"))
        if not name:
            continue
        endo = _text(li.select_one(".skill-endorsements"))
        count = int(re.sub(r"\D", "", endo)) if endo and re.search(r"\d", endo) else None
        out.append({"name": name, "endorsement_count": count})
    return out


def parse_certifications(html: str) -> list[dict]:
    soup = _soup(html)
    out: list[dict] = []
    for li in soup.select("#certifications .cert-item"):
        url_node = li.select_one("a.cert-url")
        out.append(
            {
                "name": _text(li.select_one(".cert-name")),
                "issuer": _text(li.select_one(".cert-issuer")),
                "issue_date": _text(li.select_one(".cert-date")),
                "expiration_date": _text(li.select_one(".cert-expiration")),
                "credential_id": _text(li.select_one(".cert-id")),
                "credential_url": url_node.get("href") if url_node else None,
            }
        )
    return out


def parse_languages(html: str) -> list[dict]:
    soup = _soup(html)
    out: list[dict] = []
    for li in soup.select("#languages .lang-item"):
        name = _text(li.select_one(".lang-name"))
        if not name:
            continue
        out.append({"name": name, "proficiency": _text(li.select_one(".lang-proficiency"))})
    return out
