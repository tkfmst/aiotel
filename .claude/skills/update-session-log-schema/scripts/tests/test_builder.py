"""Tests for schema_inferrer.builder."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema_inferrer.builder import build_schema, _to_pascal_case
from schema_inferrer.collector import Collector


def _collect(*objects, discriminator="type"):
    c = Collector()
    for obj in objects:
        c.add_auto(obj, discriminator)
    return c


class TestBuildSchema:
    def test_simple_object(self):
        c = _collect(
            {"type": "a", "name": "alice", "age": 30},
            {"type": "a", "name": "bob", "age": 25},
        )
        schema = build_schema(c)
        # Single group → no oneOf, just an object
        assert schema.get("type") == "object"
        props = schema["properties"]
        assert props["name"]["type"] == "string"
        assert props["age"]["type"] == "integer"
        assert props["type"] == {"const": "a"}

    def test_nullable_field(self):
        c = _collect(
            {"type": "a", "val": "hello"},
            {"type": "a", "val": None},
            {"type": "a", "val": "world"},
        )
        schema = build_schema(c)
        val_schema = schema["properties"]["val"]
        # Should be ["string", "null"]
        assert val_schema.get("type") == ["string", "null"]

    def test_enum_generation(self):
        c = _collect(
            *[{"type": "a", "status": s} for s in ["active"] * 5 + ["inactive"] * 5 + ["pending"] * 5]
        )
        schema = build_schema(c)
        status = schema["properties"]["status"]
        assert "enum" in status
        assert sorted(status["enum"]) == ["active", "inactive", "pending"]

    def test_required_fields(self):
        c = _collect(
            {"type": "a", "x": 1, "y": 2},
            {"type": "a", "x": 3},
        )
        schema = build_schema(c)
        req = schema.get("required", [])
        assert "type" in req
        assert "x" in req
        # y is only in 1/2 objects = 50%, below threshold
        assert "y" not in req

    def test_optional_fields(self):
        c = _collect(
            {"type": "a", "x": 1},
            {"type": "a", "x": 2, "opt": "hi"},
        )
        schema = build_schema(c)
        # opt should be in properties but not required
        assert "opt" in schema["properties"]
        assert "opt" not in schema.get("required", [])

    def test_discriminated_union(self):
        c = _collect(
            {"type": "user", "name": "Alice"},
            {"type": "system", "msg": "ok"},
        )
        schema = build_schema(c)
        assert "oneOf" in schema
        assert len(schema["oneOf"]) == 2
        assert "$defs" in schema

    def test_const_on_discriminator(self):
        c = _collect(
            {"type": "user", "name": "Alice"},
            {"type": "system", "msg": "ok"},
        )
        schema = build_schema(c)
        user_def = schema["$defs"]["User"]
        assert user_def["properties"]["type"] == {"const": "user"}

    def test_nested_object_schema(self):
        c = _collect(
            {"type": "a", "data": {"x": 1, "y": "hi"}},
            {"type": "a", "data": {"x": 2, "y": "lo"}},
        )
        schema = build_schema(c)
        data_schema = schema["properties"]["data"]
        assert data_schema["type"] == "object"
        assert "x" in data_schema["properties"]

    def test_array_items_schema(self):
        c = _collect(
            {"type": "a", "tags": ["x", "y"]},
            {"type": "a", "tags": ["z"]},
        )
        schema = build_schema(c)
        tags = schema["properties"]["tags"]
        assert tags["type"] == "array"
        assert tags["items"]["type"] == "string"

    def test_anyof_for_mixed_types(self):
        c = _collect(
            {"type": "a", "val": "string_value"},
            {"type": "a", "val": {"nested": True}},
        )
        schema = build_schema(c)
        val_schema = schema["properties"]["val"]
        assert "anyOf" in val_schema

    def test_generated_schema_has_draft(self):
        c = _collect({"type": "a", "x": 1})
        schema = build_schema(c, title="Test", schema_id="test.json")
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == "test.json"
        assert schema["title"] == "Test"

    def test_empty_array_field(self):
        c = _collect(
            {"type": "a", "items": []},
            {"type": "a", "items": []},
        )
        schema = build_schema(c)
        items_schema = schema["properties"]["items"]
        assert items_schema["type"] == "array"


    def test_array_items_discriminated_union(self):
        """Array items with different 'type' values should produce oneOf."""
        c = _collect(
            {"type": "msg", "content": [{"type": "text", "text": "hi"}]},
            {"type": "msg", "content": [{"type": "thinking", "thinking": "hmm", "signature": "s"}]},
            {"type": "msg", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"cmd": "ls"}}]},
            {"type": "msg", "content": [{"type": "text", "text": "bye"}, {"type": "tool_use", "id": "t2", "name": "Read", "input": {"p": "/"}}]},
        )
        schema = build_schema(c)
        content_schema = schema["properties"]["content"]
        assert content_schema["type"] == "array"
        items = content_schema["items"]
        assert "oneOf" in items, f"Expected oneOf in items, got: {list(items.keys())}"
        # Should have 3 variants: text, thinking, tool_use
        assert len(items["oneOf"]) == 3
        # Each variant should have const on type
        consts = set()
        for variant in items["oneOf"]:
            tp = variant.get("properties", {}).get("type", {})
            if "const" in tp:
                consts.add(tp["const"])
        assert consts == {"text", "thinking", "tool_use"}

    def test_array_items_discriminated_roundtrip(self):
        """Generated schema with array discriminator should validate all inputs."""
        try:
            from jsonschema import validate, Draft202012Validator
        except ImportError:
            import pytest
            pytest.skip("jsonschema not installed")

        objects = [
            {"type": "msg", "content": [{"type": "text", "text": "hi"}]},
            {"type": "msg", "content": [{"type": "thinking", "thinking": "hmm", "signature": "s"}]},
            {"type": "msg", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"cmd": "ls"}}]},
            {"type": "msg", "content": [{"type": "text", "text": "a"}, {"type": "thinking", "thinking": "b", "signature": "c"}]},
        ]
        c = _collect(*objects)
        schema = build_schema(c)
        Draft202012Validator.check_schema(schema)
        for obj in objects:
            validate(instance=obj, schema=schema)

    def test_no_false_enum_on_diverse_strings(self):
        """Fields with many unique string values should NOT produce enum."""
        objs = [{"type": "a", "name": f"file-{i}@v{j}"} for i in range(10) for j in range(3)]
        c = _collect(*objs)
        schema = build_schema(c)
        name_schema = schema["properties"]["name"]
        # 30 unique values out of 30 total → ratio 1.0 > 0.5, so no enum
        assert "enum" not in name_schema

    def test_no_false_uuid_pattern_with_mixed_ids(self):
        """UUID pattern should not apply when some values are non-UUID."""
        objs = [
            {"type": "a", "id": "550e8400-e29b-41d4-a716-446655440000"},
            {"type": "a", "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"},
            {"type": "a", "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"},
            {"type": "a", "id": "bash-progress-0"},
            {"type": "a", "id": "task-output-waiting-123"},
        ]
        c = _collect(*objs)
        schema = build_schema(c)
        id_schema = schema["properties"]["id"]
        # Should NOT have UUID pattern because not all values are UUIDs
        assert "pattern" not in id_schema

    def test_dynamic_keys_become_additional_properties(self):
        """Object with path-like keys should use additionalProperties."""
        c = _collect(
            {"type": "a", "files": {"/path/to/foo.txt": {"v": 1}, "/path/to/bar.txt": {"v": 2}}},
            {"type": "a", "files": {"/other/baz.txt": {"v": 3}}},
            {"type": "a", "files": {"/another/qux.txt": {"v": 4}}},
        )
        schema = build_schema(c)
        files_schema = schema["properties"]["files"]
        assert "additionalProperties" in files_schema
        assert "properties" not in files_schema

    def test_nullable_enum_includes_null(self):
        """Nullable enum field should include null in enum values."""
        objs = (
            [{"type": "a", "status": "ok"}] * 8
            + [{"type": "a", "status": "fail"}] * 8
            + [{"type": "a", "status": None}] * 2
        )
        c = _collect(*objs)
        schema = build_schema(c)
        status = schema["properties"]["status"]
        assert "enum" in status
        assert None in status["enum"]
        assert "null" in status["type"]

    def test_nullable_backup_filename_no_enum(self):
        """Nullable string field with varying values should not produce enum."""
        objs = [
            {"type": "b", "backup": None, "name": "file-a@v1"},
            {"type": "b", "backup": "hash@v2", "name": "file-b@v3"},
            {"type": "b", "backup": "hash@v3", "name": "file-c@v1"},
            {"type": "b", "backup": None, "name": "file-d@v1"},
        ]
        c = _collect(*objs)
        schema = build_schema(c)
        backup_schema = schema["properties"]["backup"]
        # Should be nullable string, not enum
        assert "enum" not in backup_schema


class TestToPascalCase:
    def test_snake_case(self):
        assert _to_pascal_case("hook_progress") == "HookProgress"

    def test_kebab_case(self):
        assert _to_pascal_case("file-history-snapshot") == "FileHistorySnapshot"

    def test_single_word(self):
        assert _to_pascal_case("user") == "User"

    def test_already_capitalized(self):
        assert _to_pascal_case("User") == "User"
