"""Integration tests for infer_schema.py CLI."""

import json
import os
import subprocess
import sys
import tempfile

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..")
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
CLI = os.path.join(SCRIPTS_DIR, "infer_schema.py")


def _run_cli(*args, stdin_data=None):
    """Run infer_schema.py and return (returncode, stdout, stderr)."""
    cmd = [sys.executable, CLI] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=stdin_data,
        cwd=SCRIPTS_DIR,
    )
    return result.returncode, result.stdout, result.stderr


class TestFileInput:
    def test_file_input(self):
        path = os.path.join(FIXTURES_DIR, "simple.jsonl")
        rc, stdout, stderr = _run_cli(path)
        assert rc == 0
        schema = json.loads(stdout)
        assert "$schema" in schema

    def test_directory_input(self):
        rc, stdout, stderr = _run_cli(FIXTURES_DIR)
        assert rc == 0
        schema = json.loads(stdout)
        assert "$schema" in schema

    def test_output_to_file(self):
        path = os.path.join(FIXTURES_DIR, "simple.jsonl")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            outpath = f.name
        try:
            rc, stdout, stderr = _run_cli(path, "--output", outpath)
            assert rc == 0
            with open(outpath) as f:
                schema = json.load(f)
            assert "$schema" in schema
        finally:
            os.unlink(outpath)

    def test_title_and_id(self):
        path = os.path.join(FIXTURES_DIR, "simple.jsonl")
        rc, stdout, _ = _run_cli(path, "--title", "MyTitle", "--id", "my.json")
        assert rc == 0
        schema = json.loads(stdout)
        assert schema["title"] == "MyTitle"
        assert schema["$id"] == "my.json"


class TestStdinInput:
    def test_stdin_input(self):
        data = '{"type": "a", "x": 1}\n{"type": "b", "y": 2}\n'
        rc, stdout, stderr = _run_cli(stdin_data=data)
        assert rc == 0
        schema = json.loads(stdout)
        assert "oneOf" in schema


class TestEdgeCases:
    def test_empty_input_errors(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write("")
            path = f.name
        try:
            rc, _, stderr = _run_cli(path)
            assert rc != 0
        finally:
            os.unlink(path)

    def test_invalid_json_lines_skipped(self):
        data = '{"type": "a", "x": 1}\nNOT_JSON\n{"type": "a", "x": 2}\n'
        rc, stdout, _ = _run_cli(stdin_data=data)
        assert rc == 0
        schema = json.loads(stdout)
        assert "$schema" in schema


class TestRoundtrip:
    def test_roundtrip_validation(self):
        """Generated schema should validate all input objects."""
        try:
            from jsonschema import validate, Draft202012Validator
        except ImportError:
            import pytest
            pytest.skip("jsonschema not installed")

        path = os.path.join(FIXTURES_DIR, "simple.jsonl")
        rc, stdout, _ = _run_cli(path)
        assert rc == 0
        schema = json.loads(stdout)

        Draft202012Validator.check_schema(schema)

        with open(path) as f:
            for line in f:
                obj = json.loads(line.strip())
                validate(instance=obj, schema=schema)

    def test_roundtrip_array_discriminator(self):
        """Array items with discriminator should roundtrip validate."""
        try:
            from jsonschema import validate, Draft202012Validator
        except ImportError:
            import pytest
            pytest.skip("jsonschema not installed")

        path = os.path.join(FIXTURES_DIR, "array_discriminator.jsonl")
        rc, stdout, _ = _run_cli(path)
        assert rc == 0
        schema = json.loads(stdout)
        Draft202012Validator.check_schema(schema)

        with open(path) as f:
            for line in f:
                obj = json.loads(line.strip())
                validate(instance=obj, schema=schema)

    def test_roundtrip_pattern_edge_cases(self):
        """Mixed UUID/non-UUID and nullable fields should roundtrip validate."""
        try:
            from jsonschema import validate, Draft202012Validator
        except ImportError:
            import pytest
            pytest.skip("jsonschema not installed")

        path = os.path.join(FIXTURES_DIR, "pattern_edge_cases.jsonl")
        rc, stdout, _ = _run_cli(path)
        assert rc == 0
        schema = json.loads(stdout)
        Draft202012Validator.check_schema(schema)

        with open(path) as f:
            for line in f:
                obj = json.loads(line.strip())
                validate(instance=obj, schema=schema)

    def test_roundtrip_edge_cases(self):
        """Null, empty arrays, mixed types should roundtrip validate."""
        try:
            from jsonschema import validate, Draft202012Validator
        except ImportError:
            import pytest
            pytest.skip("jsonschema not installed")

        path = os.path.join(FIXTURES_DIR, "edge_cases.jsonl")
        rc, stdout, _ = _run_cli(path)
        assert rc == 0
        schema = json.loads(stdout)
        Draft202012Validator.check_schema(schema)

        with open(path) as f:
            for line in f:
                obj = json.loads(line.strip())
                validate(instance=obj, schema=schema)

    def test_roundtrip_remaining_edge_cases(self):
        """Synthetic assistant, progress without entrypoint, image content."""
        try:
            from jsonschema import validate, Draft202012Validator
        except ImportError:
            import pytest
            pytest.skip("jsonschema not installed")

        path = os.path.join(FIXTURES_DIR, "remaining_edge_cases.jsonl")
        rc, stdout, _ = _run_cli(path)
        assert rc == 0
        schema = json.loads(stdout)
        Draft202012Validator.check_schema(schema)

        with open(path) as f:
            for i, line in enumerate(f):
                obj = json.loads(line.strip())
                validate(instance=obj, schema=schema)

    def test_real_sample_discriminated_union(self):
        """Real session log samples produce a discriminated union."""
        path = os.path.join(FIXTURES_DIR, "real_sample.jsonl")
        if not os.path.exists(path):
            import pytest
            pytest.skip("real_sample.jsonl not available")

        rc, stdout, _ = _run_cli(path)
        assert rc == 0
        schema = json.loads(stdout)
        assert "oneOf" in schema
        assert "$defs" in schema
        # Should have multiple definitions
        assert len(schema["$defs"]) >= 2
