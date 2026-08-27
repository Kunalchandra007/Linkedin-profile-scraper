"""Regenerate ``docs/schema.json`` from the Pydantic models.

The models in ``app/schemas.py`` are the single source of truth for the API
contract; this script serialises them to JSON Schema so the committed file can
never drift from the code. Run it whenever the response models change:

    python -m scripts.dump_schema
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas import EnqueueResponse, JobResponse, ProfileResult

OUT = Path(__file__).resolve().parent.parent / "docs" / "schema.json"


def build() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "LinkedIn Profile API — response schemas",
        "description": (
            "Locked response contract. `ProfileResult` is the core object returned "
            "under `data`; `EnqueueResponse`/`JobResponse` are the endpoint envelopes."
        ),
        "$defs": {
            "ProfileResult": ProfileResult.model_json_schema(),
            "EnqueueResponse": EnqueueResponse.model_json_schema(),
            "JobResponse": JobResponse.model_json_schema(),
        },
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
