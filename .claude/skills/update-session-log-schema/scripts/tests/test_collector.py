"""Tests for schema_inferrer.collector."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema_inferrer.collector import Collector, FieldInfo, _json_type_name


class TestFieldInfo:
    def test_single_string_field(self):
        fi = FieldInfo()
        fi.add_value("alice")
        assert fi.types["string"] == 1
        assert fi.count == 1

    def test_multiple_types(self):
        fi = FieldInfo()
        fi.add_value("hello")
        fi.add_value(None)
        fi.add_value("world")
        assert fi.types["string"] == 2
        assert fi.types["null"] == 1
        assert fi.count == 3

    def test_nested_object(self):
        fi = FieldInfo()
        fi.add_value({"role": "user", "text": "hi"})
        assert fi.children is not None
        assert "role" in fi.children
        assert fi.children["role"].types["string"] == 1

    def test_array_items(self):
        fi = FieldInfo()
        fi.add_value([1, 2, 3])
        assert fi.array_items is not None
        assert fi.array_items.types["integer"] == 3

    def test_mixed_array_items(self):
        fi = FieldInfo()
        fi.add_value(["a", 1])
        assert fi.array_items is not None
        assert fi.array_items.types["string"] == 1
        assert fi.array_items.types["integer"] == 1

    def test_field_count(self):
        fi = FieldInfo()
        fi.add_value("a")
        fi.add_value("b")
        assert fi.count == 2

    def test_enum_value_collection(self):
        fi = FieldInfo()
        fi.add_value("user")
        fi.add_value("assistant")
        fi.add_value("user")
        assert fi.values == {"user", "assistant"}

    def test_sample_collection_max(self):
        fi = FieldInfo()
        for i in range(100):
            fi.add_value(f"val{i}")
        assert len(fi.samples) == 50  # MAX_SAMPLES

    def test_empty_object(self):
        fi = FieldInfo()
        fi.add_value({})
        assert fi.types["object"] == 1
        assert fi.children == {}


class TestCollector:
    def test_add_auto_groups_by_type(self):
        c = Collector()
        c.add_auto({"type": "user", "name": "Alice"})
        c.add_auto({"type": "system", "msg": "ok"})
        assert "user" in c.groups
        assert "system" in c.groups
        assert c.total == 2

    def test_add_auto_no_type_field(self):
        c = Collector()
        c.add_auto({"name": "Alice"})
        assert None in c.groups
        assert c.total == 1

    def test_group_field_infos(self):
        c = Collector()
        c.add_auto({"type": "a", "x": 1})
        c.add_auto({"type": "a", "x": 2, "y": "hi"})
        group = c.groups["a"]
        assert group.total == 2
        assert "x" in group.field_infos
        assert group.field_infos["x"].count == 2
        assert group.field_infos["y"].count == 1


class TestJsonTypeName:
    def test_types(self):
        assert _json_type_name(None) == "null"
        assert _json_type_name(True) == "boolean"
        assert _json_type_name(42) == "integer"
        assert _json_type_name(3.14) == "number"
        assert _json_type_name("hi") == "string"
        assert _json_type_name([]) == "array"
        assert _json_type_name({}) == "object"
