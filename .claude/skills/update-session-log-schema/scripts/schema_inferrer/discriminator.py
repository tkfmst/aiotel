"""Detect discriminator fields in a collection of JSON objects."""

from __future__ import annotations

from typing import Any, Sequence

# Fields commonly used as discriminators, checked first.
_PREFERRED_NAMES = ("type", "kind", "subtype", "action", "event", "operation")

# Minimum fraction of objects that must have the field for it to be a candidate.
_PRESENCE_THRESHOLD = 0.95


def find_discriminator(
    objects: Sequence[dict[str, Any]],
    *,
    presence_threshold: float = _PRESENCE_THRESHOLD,
) -> str | None:
    """Return the best discriminator field name, or None if none found.

    A discriminator field must:
    1. Be present in >= presence_threshold of all objects.
    2. Always be a string value (when present).
    3. Have more than one unique value.
    4. Have at least two groups with noticeably different field sets.
    """
    if len(objects) < 2:
        return None

    n = len(objects)
    min_count = int(n * presence_threshold)

    # Gather candidate fields: present often enough and always string.
    candidates: dict[str, set[str]] = {}
    field_counts: dict[str, int] = {}

    for obj in objects:
        for key, value in obj.items():
            field_counts[key] = field_counts.get(key, 0) + 1
            if isinstance(value, str):
                if key not in candidates:
                    candidates[key] = set()
                candidates[key].add(value)

    # Filter: must be present often enough, always string, >1 unique value.
    valid: list[tuple[str, set[str]]] = []
    for key, values in candidates.items():
        if field_counts.get(key, 0) < min_count:
            continue
        if len(values) < 2:
            continue
        # Verify it's always string when present.
        all_string = all(
            isinstance(obj.get(key), str) for obj in objects if key in obj
        )
        if not all_string:
            continue
        # Check that different values correspond to different field sets.
        if _has_structural_variance(objects, key):
            valid.append((key, values))

    if not valid:
        return None

    # Prefer well-known names.
    for preferred in _PREFERRED_NAMES:
        for key, _ in valid:
            if key == preferred:
                return key

    # Fall back to candidate with most unique values.
    valid.sort(key=lambda kv: len(kv[1]), reverse=True)
    return valid[0][0]


def _has_structural_variance(
    objects: Sequence[dict[str, Any]], field: str
) -> bool:
    """Check whether objects grouped by field[value] have different key sets."""
    groups: dict[str, set[str]] = {}
    for obj in objects:
        val = obj.get(field)
        if not isinstance(val, str):
            continue
        keys = frozenset(k for k in obj if k != field)
        if val not in groups:
            groups[val] = set(keys)
        else:
            groups[val] |= keys

    if len(groups) < 2:
        return False

    key_sets = list(groups.values())
    # At least one pair of groups must differ in their field sets.
    for i in range(len(key_sets)):
        for j in range(i + 1, len(key_sets)):
            if key_sets[i] != key_sets[j]:
                return True
    return False
