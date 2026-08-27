"""Parser unit tests — run against saved HTML fixtures, no live LinkedIn."""

from app.providers import linkedin_parsers as p


def test_top_card(full_html):
    tc = p.parse_top_card(full_html)
    assert tc["name"] == "Ada Lovelace"
    assert tc["headline"] == "Mathematician · First Programmer"
    assert "London" in tc["location"]
    assert tc["profile_photo_url"].endswith("ada-avatar.jpg")
    assert tc["banner_photo_url"].endswith("ada-banner.jpg")


def test_about(full_html):
    assert "Analytical Engine" in p.parse_about(full_html)


def test_experience(full_html):
    exp = p.parse_experience(full_html)
    assert len(exp) == 2

    assert exp[0]["title"] == "Collaborator"
    assert exp[0]["company"] == "Analytical Engine Project"
    assert exp[0]["employment_type"] == "Full-time"
    assert exp[0]["start_date"] == "Jan 1842"
    assert exp[0]["end_date"] is None
    assert exp[0]["is_current"] is True

    assert exp[1]["company"] == "Self-employed"
    assert exp[1]["employment_type"] is None
    assert exp[1]["start_date"] == "1840"
    assert exp[1]["end_date"] == "1842"
    assert exp[1]["is_current"] is False


def test_education(full_html):
    edu = p.parse_education(full_html)
    assert edu[0]["school"] == "Private Tutoring"
    assert edu[0]["degree"] == "Private Study"
    assert edu[0]["field_of_study"] == "Mathematics"


def test_skills(full_html):
    skills = {s["name"]: s["endorsement_count"] for s in p.parse_skills(full_html)}
    assert skills["Mathematics"] == 99
    assert skills["Algorithms"] == 42
    assert skills["Technical Writing"] is None


def test_certifications(full_html):
    certs = p.parse_certifications(full_html)
    assert certs[0]["name"].startswith("Fellow")
    assert certs[0]["issuer"] == "Analytical Society"
    assert certs[0]["credential_url"].endswith("/credential/ada")


def test_languages(full_html):
    langs = {lang["name"] for lang in p.parse_languages(full_html)}
    assert langs == {"English", "French"}


def test_minimal_profile_degrades(minimal_html):
    assert p.parse_top_card(minimal_html)["name"] == "Restricted Member"
    assert p.parse_top_card(minimal_html)["headline"] is None
    assert p.parse_experience(minimal_html) == []
    assert p.parse_skills(minimal_html) == []
    assert p.parse_languages(minimal_html) == []
