import pytest

from app.urls import InvalidLinkedInURL, normalize_linkedin_url, profile_slug


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.linkedin.com/in/jane-doe/", "https://www.linkedin.com/in/jane-doe"),
        ("http://linkedin.com/in/jane-doe?originalSubdomain=uk", "https://www.linkedin.com/in/jane-doe"),
        ("linkedin.com/in/jane-doe", "https://www.linkedin.com/in/jane-doe"),
        ("https://uk.linkedin.com/in/jane-doe", "https://www.linkedin.com/in/jane-doe"),
        ("  https://www.linkedin.com/in/jane-doe  ", "https://www.linkedin.com/in/jane-doe"),
    ],
)
def test_normalize_valid(raw, expected):
    assert normalize_linkedin_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not a url",
        "https://example.com/in/jane",
        "https://www.linkedin.com/company/acme",
        "https://www.linkedin.com/feed/",
        "https://www.linkedin.com/in/",
    ],
)
def test_normalize_invalid(raw):
    with pytest.raises(InvalidLinkedInURL):
        normalize_linkedin_url(raw)


def test_profile_slug():
    assert profile_slug("https://www.linkedin.com/in/jane-doe") == "jane-doe"
