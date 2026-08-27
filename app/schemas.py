"""Pydantic models: the request body, the locked-in profile response schema,
and the async job envelopes. This module is the single source of truth for the
API contract — `docs/schema.json` is generated from it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.urls import InvalidLinkedInURL, normalize_linkedin_url

# ─────────────────────────── Profile sub-sections ───────────────────────────


class Experience(BaseModel):
    title: str | None = Field(None, description="Job title / role")
    company: str | None = Field(None, description="Employer name")
    employment_type: str | None = Field(None, description="Full-time, Contract, etc.")
    location: str | None = Field(None, description="Role location, if shown")
    start_date: str | None = Field(None, description="Free-text start, e.g. 'Jan 2021'")
    end_date: str | None = Field(None, description="Free-text end, or null if current")
    is_current: bool = Field(False, description="True if this is a current role")
    description: str | None = Field(None, description="Role description / bullets")


class Education(BaseModel):
    school: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None


class Skill(BaseModel):
    name: str
    endorsement_count: int | None = Field(None, description="Endorsements, if visible")


class Certification(BaseModel):
    name: str | None = None
    issuer: str | None = None
    issue_date: str | None = None
    expiration_date: str | None = None
    credential_id: str | None = None
    credential_url: str | None = None


class Language(BaseModel):
    name: str
    proficiency: str | None = Field(None, description="e.g. 'Native or bilingual'")


class Profile(BaseModel):
    """The extracted profile. Unavailable fields are ``null`` (scalars) or an
    empty list (sections) — never missing — so clients can rely on the shape."""

    name: str | None = None
    headline: str | None = None
    location: str | None = None
    about: str | None = None
    profile_photo_url: str | None = None
    banner_photo_url: str | None = None
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)


# ─────────────────────────── Top-level envelopes ────────────────────────────


class ProfileResult(BaseModel):
    """A completed scrape/lookup result. This is the object stored in the cache
    and returned under `data` when a job is done."""

    url: str = Field(description="Canonical profile URL this result is for")
    source: str = Field(description="Which provider produced it: mock | fixture | linkedin")
    scraped_at: datetime = Field(description="UTC timestamp the data was obtained")
    profile: Profile
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues, e.g. a section was restricted or truncated",
    )


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


class ProfileRequest(BaseModel):
    url: str = Field(description="A public LinkedIn profile URL (linkedin.com/in/<slug>)")

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        try:
            return normalize_linkedin_url(v)
        except InvalidLinkedInURL as exc:
            raise ValueError(str(exc)) from exc


class EnqueueResponse(BaseModel):
    """Returned by POST /api/v1/profile. On a cache hit `cached` is true,
    `status` is `done`, and `data` is populated immediately (HTTP 200).
    On a miss the job is queued (HTTP 202)."""

    job_id: str
    status: JobStatus
    url: str
    cached: bool = False
    data: ProfileResult | None = None


class JobResponse(BaseModel):
    """Returned by GET /api/v1/profile/{job_id}."""

    job_id: str
    status: JobStatus
    url: str
    data: ProfileResult | None = None
    error: str | None = None


class ProviderHealth(BaseModel):
    provider: str
    ok: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    provider: ProviderHealth
