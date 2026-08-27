"""End-to-end API tests — exercised against the `fixture` provider via the ASGI app.

No network, no credentials: the inline worker processes jobs in-process and every
profile comes from a canned fixture on disk.
"""

import asyncio

import pytest

from tests.conftest import AUTH

ADA_URL = "https://www.linkedin.com/in/ada-lovelace"
MISSING_URL = "https://www.linkedin.com/in/nobody-here-xyz"


async def _poll_until_terminal(client, job_id, *, timeout=10.0):
    """Poll the job endpoint until the inline worker reaches done/error."""
    deadline = 0.0
    while deadline < timeout:
        resp = await client.get(f"/api/v1/profile/{job_id}", headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("done", "error"):
            return body
        await asyncio.sleep(0.05)
        deadline += 0.05
    pytest.fail(f"job {job_id} did not finish within {timeout}s")


async def test_health_is_public_and_reports_provider(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["provider"]["provider"] == "fixture"


async def test_post_requires_api_key(client):
    resp = await client.post("/api/v1/profile", json={"url": ADA_URL})
    assert resp.status_code == 401


async def test_post_rejects_invalid_url(client):
    resp = await client.post("/api/v1/profile", json={"url": "https://example.com/in/x"}, headers=AUTH)
    assert resp.status_code == 422


async def test_enqueue_poll_and_complete(client):
    resp = await client.post("/api/v1/profile", json={"url": ADA_URL}, headers=AUTH)
    assert resp.status_code == 202
    enq = resp.json()
    assert enq["status"] == "queued"
    assert enq["cached"] is False

    final = await _poll_until_terminal(client, enq["job_id"])
    assert final["status"] == "done"
    assert final["data"]["profile"]["name"] == "Ada Lovelace"
    assert final["data"]["source"] == "fixture"


async def test_second_request_is_served_from_cache(client):
    first = await client.post("/api/v1/profile", json={"url": ADA_URL}, headers=AUTH)
    await _poll_until_terminal(client, first.json()["job_id"])

    second = await client.post("/api/v1/profile", json={"url": ADA_URL}, headers=AUTH)
    assert second.status_code == 200  # cache hit short-circuits the queue
    body = second.json()
    assert body["cached"] is True
    assert body["status"] == "done"
    assert body["data"]["profile"]["name"] == "Ada Lovelace"


async def test_unknown_job_returns_404(client):
    resp = await client.get("/api/v1/profile/deadbeef", headers=AUTH)
    assert resp.status_code == 404


async def test_profile_not_found_ends_in_error(client):
    resp = await client.post("/api/v1/profile", json={"url": MISSING_URL}, headers=AUTH)
    assert resp.status_code == 202
    final = await _poll_until_terminal(client, resp.json()["job_id"])
    assert final["status"] == "error"
    assert final["error"]
