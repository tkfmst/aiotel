"""Tests for schema_inferrer.discriminator."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema_inferrer.discriminator import find_discriminator


class TestFindDiscriminator:
    def test_detect_type_field(self):
        objects = [
            {"type": "a", "x": 1},
            {"type": "b", "y": 2},
        ]
        assert find_discriminator(objects) == "type"

    def test_no_discriminator_same_structure(self):
        objects = [
            {"x": 1, "y": 2},
            {"x": 3, "y": 4},
        ]
        assert find_discriminator(objects) is None

    def test_non_string_field_ignored(self):
        objects = [
            {"type": 123, "x": 1},
            {"type": 456, "y": 2},
        ]
        assert find_discriminator(objects) is None

    def test_single_value_not_discriminator(self):
        objects = [
            {"type": "a", "x": 1},
            {"type": "a", "y": 2},
        ]
        assert find_discriminator(objects) is None

    def test_optional_field_ignored(self):
        objects = [
            {"type": "a", "x": 1},
            {"y": 2},
            {"y": 3},
            {"y": 4},
            {"type": "b", "z": 3},
        ]
        # type is present in 2/5 = 40%, below 95% threshold
        assert find_discriminator(objects) is None

    def test_multiple_candidates_prefers_type(self):
        objects = [
            {"type": "a", "kind": "x", "val": 1},
            {"type": "b", "kind": "y", "other": 2},
        ]
        assert find_discriminator(objects) == "type"

    def test_single_object(self):
        assert find_discriminator([{"type": "a"}]) is None

    def test_empty_list(self):
        assert find_discriminator([]) is None

    def test_kind_field_when_no_type(self):
        objects = [
            {"kind": "click", "x": 10},
            {"kind": "scroll", "delta": 5},
        ]
        assert find_discriminator(objects) == "kind"
