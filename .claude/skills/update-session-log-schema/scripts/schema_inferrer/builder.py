"""Build JSON Schema from collected field information."""

from __future__ import annotations

import re
from typing import Any

from .collector import Collector, FieldInfo, GroupInfo
from .discriminator import find_discriminator
from .patterns import detect_pattern

# Thresholds
DEFAULT_REQUIRED_THRESHOLD = 0.95
DEFAULT_ENUM_MAX = 20
DEFAULT_ENUM_MIN_COVERAGE = 0.80


class SchemaBuilder:
    """Build a JSON Schema (Draft 2020-12) from a Collector's data."""

    def __init__(
        self,
        *,
        required_threshold: float = DEFAULT_REQUIRED_THRESHOLD,
        enum_max: int = DEFAULT_ENUM_MAX,
        title: str | None = None,
        schema_id: str | None = None,
    ) -> None:
        self.required_threshold = required_threshold
        self.enum_max = enum_max
        self.title = title
        self.schema_id = schema_id
        self._defs: dict[str, dict] = {}
        self._suppress_enum = False  # Suppress enum in additionalProperties context

    def build(self, collector: Collector) -> dict[str, Any]:
        """Build the top-level schema from a Collector."""
        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
        }
        if self.schema_id:
            schema["$id"] = self.schema_id
        if self.title:
            schema["title"] = self.title

        self._defs = {}

        groups = collector.groups
        non_none_groups = {k: v for k, v in groups.items() if k is not None}

        if len(non_none_groups) >= 2:
            # Discriminated union at top level.
            refs = []
            for key in sorted(non_none_groups):
                def_name = _to_pascal_case(key)
                group = non_none_groups[key]
                self._defs[def_name] = self._build_group_schema(group, key)
                refs.append({"$ref": f"#/$defs/{def_name}"})
            schema["oneOf"] = refs
        elif len(non_none_groups) == 1:
            key = next(iter(non_none_groups))
            group = non_none_groups[key]
            schema.update(self._build_group_schema(group, key))
        elif None in groups:
            group = groups[None]
            schema.update(self._build_group_schema(group, None))

        if self._defs:
            schema["$defs"] = dict(sorted(self._defs.items()))

        return schema

    def _build_group_schema(
        self, group: GroupInfo, discriminator_value: str | None
    ) -> dict[str, Any]:
        """Build schema for a single group (one discriminator value)."""
        return self._build_object_schema(
            group.field_infos,
            group.total,
            discriminator_field="type" if discriminator_value is not None else None,
            discriminator_value=discriminator_value,
        )

    def _build_object_schema(
        self,
        fields: dict[str, FieldInfo],
        parent_count: int,
        *,
        discriminator_field: str | None = None,
        discriminator_value: str | None = None,
    ) -> dict[str, Any]:
        """Build an object schema from field infos."""
        # Detect dynamic-key objects (e.g., file paths as keys).
        if _looks_like_dynamic_keys(fields, parent_count):
            merged = _merge_field_infos(fields.values())
            prev = self._suppress_enum
            self._suppress_enum = True
            val_schema = self._build_field_schema(merged, merged.count)
            self._suppress_enum = prev
            return {"type": "object", "additionalProperties": val_schema}

        properties: dict[str, Any] = {}
        required: list[str] = []

        for name in sorted(fields):
            info = fields[name]

            if name == discriminator_field and discriminator_value is not None:
                properties[name] = {"const": discriminator_value}
            else:
                properties[name] = self._build_field_schema(info, parent_count)

            if parent_count > 0:
                rate = info.count / parent_count
                if rate >= self.required_threshold:
                    required.append(name)

        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = sorted(required)
        return schema

    def _build_field_schema(
        self, info: FieldInfo, parent_count: int
    ) -> dict[str, Any]:
        """Build schema for a single field."""
        observed = set(info.types.keys())
        non_null = observed - {"null"}

        # Single type shortcuts.
        if observed == {"string"}:
            return self._build_string_schema(info)
        if observed == {"integer"}:
            return {"type": "integer"}
        if observed == {"number"} or observed == {"integer", "number"}:
            return {"type": "number"}
        if observed == {"boolean"}:
            return {"type": "boolean"}

        # Object only — check for nested discriminator.
        if observed == {"object"} and info.children:
            nested_discrim = self._check_nested_discriminator(info)
            if nested_discrim:
                return nested_discrim
            return self._build_object_schema(info.children, info.types["object"])

        # Array only.
        if observed == {"array"}:
            return self._build_array_schema(info)

        # Nullable variants (exactly one non-null type + null).
        if "null" in observed and len(non_null) == 1:
            base_type = next(iter(non_null))
            if base_type == "string":
                base = self._build_string_schema(info)
                if "type" in base:
                    base["type"] = [base["type"], "null"]
                # If enum is present, add null to the enum too.
                if "enum" in base:
                    base["enum"] = sorted(base["enum"]) + [None]
                return base
            if base_type in ("integer", "number", "boolean"):
                return {"type": [base_type, "null"]}
            if base_type == "object" and info.children:
                obj_schema = self._build_object_schema(info.children, info.types.get("object", 0))
                return {"oneOf": [obj_schema, {"type": "null"}]}
            if base_type == "array":
                arr_schema = self._build_array_schema(info)
                return {"oneOf": [arr_schema, {"type": "null"}]}

        # Mixed types (e.g., object + string, string + integer).
        return self._build_anyof_schema(info, parent_count)

    def _build_string_schema(self, info: FieldInfo) -> dict[str, Any]:
        """Build schema for a string field, with enum/pattern detection."""
        str_samples = [s for s in info.samples if isinstance(s, str)]
        str_count = info.types.get("string", 0)

        # Check for well-known patterns (only if all samples match).
        pattern = detect_pattern(str_samples)
        if pattern:
            return pattern

        # Skip enum in suppressed contexts (e.g., additionalProperties).
        if self._suppress_enum:
            return {"type": "string"}

        # Check for enum: must have few unique values relative to total count,
        # and values should look like identifiers (short, no long prose).
        n_unique = len(info.values)
        if 1 < n_unique <= self.enum_max and str_count >= 5:
            # Ratio of unique values to total occurrences must be low enough
            # to indicate a fixed set rather than free-form text.
            ratio = n_unique / str_count
            max_len = max((len(v) for v in info.values), default=0)
            if ratio <= 0.3 and max_len <= 60:
                return {"type": "string", "enum": sorted(info.values)}

        return {"type": "string"}

    def _build_array_schema(self, info: FieldInfo) -> dict[str, Any]:
        """Build schema for an array field."""
        if info.array_items is None or info.array_items.count == 0:
            return {"type": "array"}

        # If array contains objects, check for discriminator in items.
        if info.array_item_objects and len(info.array_item_objects) >= 2:
            from .discriminator import find_discriminator

            disc = find_discriminator(info.array_item_objects)
            if disc:
                items_schema = self._build_array_items_union(
                    info.array_item_objects, disc, info
                )
                return {"type": "array", "items": items_schema}

        items_schema = self._build_field_schema(
            info.array_items, info.array_items.count
        )
        if not items_schema:
            return {"type": "array"}
        return {"type": "array", "items": items_schema}

    def _build_array_items_union(
        self,
        objects: list[dict],
        discriminator: str,
        parent_info: "FieldInfo",
    ) -> dict[str, Any]:
        """Build a oneOf schema for array items grouped by discriminator."""
        from .collector import Collector

        sub_collector = Collector()
        for obj in objects:
            sub_collector.add_auto(obj, discriminator)

        non_dict_types = set(parent_info.array_items.types.keys()) - {"object"}

        # Suppress enum in array items union — samples are too small per variant.
        prev = self._suppress_enum
        self._suppress_enum = True

        variants: list[dict[str, Any]] = []
        for key in sorted(sub_collector.groups):
            if key is None:
                continue
            group = sub_collector.groups[key]
            group_schema = self._build_object_schema(
                group.field_infos,
                group.total,
                discriminator_field=discriminator,
                discriminator_value=key,
            )
            variants.append(group_schema)

        self._suppress_enum = prev

        # Add non-object types if present (e.g., string items mixed in).
        for t in sorted(non_dict_types):
            if t == "string":
                variants.append({"type": "string"})
            elif t == "integer":
                variants.append({"type": "integer"})
            elif t == "number":
                variants.append({"type": "number"})
            elif t == "boolean":
                variants.append({"type": "boolean"})
            elif t == "null":
                variants.append({"type": "null"})

        if len(variants) == 1:
            return variants[0]
        return {"oneOf": variants}

    def _build_anyof_schema(
        self, info: FieldInfo, parent_count: int
    ) -> dict[str, Any]:
        """Build anyOf schema for mixed-type fields."""
        variants: list[dict[str, Any]] = []
        observed = set(info.types.keys())

        for t in sorted(observed):
            if t == "null":
                variants.append({"type": "null"})
            elif t == "string":
                variants.append(self._build_string_schema(info))
            elif t == "integer":
                variants.append({"type": "integer"})
            elif t == "number":
                variants.append({"type": "number"})
            elif t == "boolean":
                variants.append({"type": "boolean"})
            elif t == "object" and info.children:
                variants.append(
                    self._build_object_schema(info.children, info.types["object"])
                )
            elif t == "array":
                variants.append(self._build_array_schema(info))

        if not variants:
            return {}
        if len(variants) == 1:
            return variants[0]
        return {"anyOf": variants}

    def _check_nested_discriminator(self, info: FieldInfo) -> dict[str, Any] | None:
        """Check if a nested object field has a discriminator, and build oneOf."""
        if not info.children:
            return None

        # Rebuild the raw objects from children to check for discriminator.
        # We can detect it if children contain a field with multiple const-like values.
        candidate_field = None
        for fname, finfo in info.children.items():
            if (
                set(finfo.types.keys()) <= {"string"}
                and len(finfo.values) >= 2
                and finfo.count >= info.types.get("object", 1) * 0.9
            ):
                candidate_field = fname
                break

        if candidate_field is None:
            return self._build_object_schema(info.children, info.types.get("object", 0))

        # Group children by the candidate field's values.
        # This is approximate: we use the FieldInfo data, not raw objects.
        # For proper grouping, the Collector should be used at a higher level.
        return self._build_object_schema(info.children, info.types.get("object", 0))


def build_schema(
    collector: Collector,
    *,
    title: str | None = None,
    schema_id: str | None = None,
    required_threshold: float = DEFAULT_REQUIRED_THRESHOLD,
    enum_max: int = DEFAULT_ENUM_MAX,
) -> dict[str, Any]:
    """Convenience function to build a schema from a collector."""
    builder = SchemaBuilder(
        required_threshold=required_threshold,
        enum_max=enum_max,
        title=title,
        schema_id=schema_id,
    )
    return builder.build(collector)


def _to_pascal_case(snake: str) -> str:
    """Convert a snake_case or kebab-case string to PascalCase."""
    parts = re.split(r"[-_]", snake)
    return "".join(p.capitalize() for p in parts if p)


def _looks_like_dynamic_keys(
    fields: dict[str, "FieldInfo"], parent_count: int
) -> bool:
    """Heuristic: detect objects whose keys are dynamic (e.g., file paths).

    Signals:
    - Keys contain path separators or other non-identifier characters
    - Many unique keys relative to parent count with low reuse
    """
    if len(fields) < 3 or parent_count < 3:
        return False

    path_like = sum(1 for k in fields if "/" in k or "\\" in k)
    if path_like > len(fields) * 0.5:
        return True

    # Most keys appear in very few objects, and there are many keys.
    low_reuse = sum(1 for f in fields.values() if f.count <= 2)
    if low_reuse > len(fields) * 0.7 and len(fields) >= 10:
        return True

    return False


def _merge_field_infos(infos) -> "FieldInfo":
    """Merge multiple FieldInfos into one (for additionalProperties)."""
    from .collector import FieldInfo as FI

    merged = FI()
    for info in infos:
        for type_name, count in info.types.items():
            merged.types[type_name] += count
        merged.count += info.count
        merged.values |= info.values
        merged.samples.extend(info.samples[:5])

        if info.children:
            if merged.children is None:
                merged.children = {}
            for k, v in info.children.items():
                if k in merged.children:
                    # Simple merge: accumulate counts
                    for tn, c in v.types.items():
                        merged.children[k].types[tn] += c
                    merged.children[k].count += v.count
                else:
                    merged.children[k] = v

    # Trim samples
    merged.samples = merged.samples[:50]
    return merged
