"""Collect field-level type information from JSON objects."""

from __future__ import annotations

from collections import Counter
from typing import Any

MAX_SAMPLES = 50
MAX_UNIQUE_VALUES = 200


class FieldInfo:
    """Accumulated statistics for a single field across many objects."""

    __slots__ = (
        "types", "count", "values", "samples", "children",
        "array_items", "array_item_objects",
    )

    def __init__(self) -> None:
        self.types: Counter[str] = Counter()
        self.count: int = 0
        self.values: set[str] = set()
        self.samples: list[Any] = []
        self.children: dict[str, FieldInfo] | None = None
        self.array_items: FieldInfo | None = None
        self.array_item_objects: list[dict] | None = None

    def add_value(self, value: Any) -> None:
        self.count += 1
        type_name = _json_type_name(value)
        self.types[type_name] += 1

        if isinstance(value, str) and len(self.values) < MAX_UNIQUE_VALUES:
            self.values.add(value)

        if len(self.samples) < MAX_SAMPLES and value is not None:
            self.samples.append(value)

        if isinstance(value, dict):
            if self.children is None:
                self.children = {}
            _merge_object(self.children, value)

        elif isinstance(value, list):
            if self.array_items is None:
                self.array_items = FieldInfo()
            for item in value:
                self.array_items.add_value(item)
                # Collect raw dict items for discriminator detection in arrays.
                if isinstance(item, dict):
                    if self.array_item_objects is None:
                        self.array_item_objects = []
                    if len(self.array_item_objects) < 500:
                        self.array_item_objects.append(item)


class Collector:
    """Collects per-field statistics grouped by a potential discriminator value."""

    def __init__(self) -> None:
        self.groups: dict[str | None, GroupInfo] = {}
        self.total: int = 0

    def add(self, obj: dict[str, Any], group_key: str | None = None) -> None:
        """Add a JSON object, optionally keyed by a discriminator value."""
        self.total += 1
        if group_key not in self.groups:
            self.groups[group_key] = GroupInfo(group_key)
        self.groups[group_key].add(obj)

    def add_auto(self, obj: dict[str, Any], discriminator: str = "type") -> None:
        """Add with automatic grouping by the given field (if present)."""
        key = obj.get(discriminator) if isinstance(obj.get(discriminator), str) else None
        self.add(obj, key)


class GroupInfo:
    """Statistics for a set of objects sharing the same discriminator value."""

    def __init__(self, discriminator_value: str | None) -> None:
        self.discriminator_value = discriminator_value
        self.field_infos: dict[str, FieldInfo] = {}
        self.total: int = 0

    def add(self, obj: dict[str, Any]) -> None:
        self.total += 1
        _merge_object(self.field_infos, obj)


def _merge_object(fields: dict[str, FieldInfo], obj: dict[str, Any]) -> None:
    for key, value in obj.items():
        if key not in fields:
            fields[key] = FieldInfo()
        fields[key].add_value(value)


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"
