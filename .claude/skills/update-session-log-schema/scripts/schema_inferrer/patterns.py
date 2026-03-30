"""Detect string value patterns (UUID, ISO 8601, URI) from sample values."""

from __future__ import annotations

import re
from typing import Sequence

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
_URI_RE = re.compile(r"^https?://")


def detect_pattern(samples: Sequence[str]) -> dict | None:
    """Return a JSON Schema fragment for the detected pattern, or None.

    A pattern is only reported when *every* sample matches it.
    At least 3 samples are required to avoid false positives.
    """
    if len(samples) < 3:
        return None

    if all(_UUID_RE.match(s) for s in samples):
        return {
            "type": "string",
            "pattern": r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        }

    if all(_ISO8601_RE.match(s) for s in samples):
        return {"type": "string", "format": "date-time"}

    if all(_URI_RE.match(s) for s in samples):
        return {"type": "string", "format": "uri"}

    return None
