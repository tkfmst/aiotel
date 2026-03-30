#!/usr/bin/env python3
"""Generate JSON Schema from JSONL session logs.

Usage:
    python3 infer_schema.py [inputs ...] [options]

    inputs: Files or directories. If omitted, reads JSONL from stdin.
    Directories are scanned recursively for *.jsonl files.

Examples:
    python3 infer_schema.py ~/.claude/projects/ --title "Session Log"
    python3 infer_schema.py session1.jsonl session2.jsonl
    cat *.jsonl | python3 infer_schema.py
    find ~/.claude/projects -name '*.jsonl' -mtime -5 | xargs cat | python3 infer_schema.py
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import IO, Iterator

from schema_inferrer.builder import build_schema
from schema_inferrer.collector import Collector


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate JSON Schema from JSONL session logs."
    )
    p.add_argument(
        "inputs",
        nargs="*",
        help="Input files or directories (reads *.jsonl recursively). "
        "If omitted, reads from stdin.",
    )
    p.add_argument("--output", "-o", help="Output file (default: stdout)")
    p.add_argument("--title", help="Schema title")
    p.add_argument("--id", dest="schema_id", help="Schema $id")
    p.add_argument(
        "--discriminator",
        default="type",
        help="Top-level discriminator field name (default: type)",
    )
    p.add_argument(
        "--enum-max",
        type=int,
        default=20,
        help="Max unique values for enum detection (default: 20)",
    )
    p.add_argument(
        "--required-threshold",
        type=float,
        default=0.95,
        help="Min occurrence rate for required fields (default: 0.95)",
    )
    return p.parse_args(argv)


def iter_jsonl_lines(stream: IO[str]) -> Iterator[dict]:
    """Yield parsed JSON objects from a stream, skipping invalid lines."""
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                yield obj
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue


def collect_inputs(inputs: list[str]) -> list[str]:
    """Expand directories into .jsonl file paths."""
    files: list[str] = []
    for path in inputs:
        path = os.path.expanduser(path)
        if os.path.isdir(path):
            files.extend(
                sorted(glob.glob(os.path.join(path, "**", "*.jsonl"), recursive=True))
            )
        elif os.path.isfile(path):
            files.append(path)
        else:
            print(f"Warning: skipping {path} (not found)", file=sys.stderr)
    return files


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    collector = Collector()
    count = 0

    if args.inputs:
        files = collect_inputs(args.inputs)
        if not files:
            print("Error: no .jsonl files found.", file=sys.stderr)
            return 1
        for fpath in files:
            with open(fpath) as f:
                for obj in iter_jsonl_lines(f):
                    collector.add_auto(obj, args.discriminator)
                    count += 1
    else:
        if sys.stdin.isatty():
            print("Error: no input. Provide files/directories or pipe JSONL to stdin.", file=sys.stderr)
            return 1
        for obj in iter_jsonl_lines(sys.stdin):
            collector.add_auto(obj, args.discriminator)
            count += 1

    if count == 0:
        print("Error: no valid JSON objects found.", file=sys.stderr)
        return 1

    print(f"Processed {count} objects in {len(collector.groups)} groups.", file=sys.stderr)

    schema = build_schema(
        collector,
        title=args.title,
        schema_id=args.schema_id,
        required_threshold=args.required_threshold,
        enum_max=args.enum_max,
    )

    output = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Schema written to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
