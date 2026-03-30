"""Tests for schema_inferrer.patterns."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schema_inferrer.patterns import detect_pattern


class TestDetectPattern:
    def test_uuid_detection(self):
        samples = [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        ]
        result = detect_pattern(samples)
        assert result is not None
        assert result["type"] == "string"
        assert "pattern" in result

    def test_non_uuid_string(self):
        samples = ["hello", "world"]
        result = detect_pattern(samples)
        # "hello" is not a UUID, so no pattern
        assert result is None

    def test_iso8601_detection(self):
        samples = [
            "2026-03-28T09:02:07.229Z",
            "2026-01-15T12:30:00.000Z",
            "2025-12-01T00:00:00.000Z",
        ]
        result = detect_pattern(samples)
        assert result is not None
        assert result.get("format") == "date-time"

    def test_non_datetime_string(self):
        samples = ["2026-03-28", "2026-01-15"]
        result = detect_pattern(samples)
        assert result is None

    def test_url_detection(self):
        samples = [
            "https://github.com/example/repo",
            "https://example.com/path",
            "https://api.example.com/v1",
        ]
        result = detect_pattern(samples)
        assert result is not None
        assert result.get("format") == "uri"

    def test_mixed_samples_no_pattern(self):
        samples = [
            "550e8400-e29b-41d4-a716-446655440000",
            "not-a-uuid-at-all",
        ]
        result = detect_pattern(samples)
        assert result is None

    def test_empty_samples(self):
        result = detect_pattern([])
        assert result is None

    def test_single_sample_insufficient(self):
        result = detect_pattern(["550e8400-e29b-41d4-a716-446655440000"])
        assert result is None

    def test_two_samples_insufficient(self):
        result = detect_pattern([
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        ])
        assert result is None
