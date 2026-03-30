#!/usr/bin/env python3
"""Claude Code セッションログを JSON Schema でバリデーションする。

Usage:
    python3 validate_schema.py <schema.json> <base_dir> [--days N] [--since DATE] [--until DATE] [--full]

Requires: pip install jsonschema
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from jsonschema import validate, ValidationError, Draft202012Validator
except ImportError:
    print("jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="Validate session logs against JSON Schema")
    parser.add_argument("schema_path", help="Path to session-log-message.schema.json")
    parser.add_argument("base_dir", help="Base directory (e.g., ~/.claude/projects)")
    parser.add_argument("--days", type=int, default=5, help="Only check logs modified within N days (default: 5)")
    parser.add_argument("--since", type=str, help="Only check logs since this date (YYYY-MM-DD)")
    parser.add_argument("--until", type=str, help="Only check logs until this date (YYYY-MM-DD)")
    parser.add_argument("--full", action="store_true", help="Check all logs (no date filter)")
    return parser.parse_args()


def get_date_range(args):
    if args.full:
        return None, None
    now = datetime.now(timezone.utc)
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        since = now - timedelta(days=args.days)
    if args.until:
        until = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
    else:
        until = now
    return since.timestamp(), until.timestamp()


def collect_files(base_dir, since_ts, until_ts):
    pattern = os.path.join(base_dir, "*", "*.jsonl")
    files = glob.glob(pattern)
    if since_ts is None:
        return files
    return [f for f in files if since_ts <= os.path.getmtime(f) <= until_ts]


def main():
    args = parse_args()
    schema_path = os.path.expanduser(args.schema_path)
    base_dir = os.path.expanduser(args.base_dir)

    with open(schema_path) as f:
        schema = json.load(f)

    Draft202012Validator.check_schema(schema)

    since_ts, until_ts = get_date_range(args)
    files = collect_files(base_dir, since_ts, until_ts)

    if not files:
        print("No log files found in the specified date range.", file=sys.stderr)
        sys.exit(1)

    total = 0
    errors = 0
    error_types = {}

    for fpath in files:
        with open(fpath) as f:
            for line in f:
                total += 1
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                try:
                    validate(instance=obj, schema=schema)
                except ValidationError as e:
                    errors += 1
                    t = obj.get("type", "unknown")
                    if t not in error_types:
                        error_types[t] = {"count": 0, "first_error": str(e.message)[:300]}
                    error_types[t]["count"] += 1

    passed = total - errors
    pct = (passed / total * 100) if total else 0

    print(f"Files: {len(files)}")
    print(f"Total: {total} messages")
    print(f"Pass: {passed}, Fail: {errors}")
    print(f"Pass rate: {pct:.1f}%")

    if error_types:
        print(f"\nErrors by type:")
        for t, info in sorted(error_types.items()):
            print(f"  {t}: {info['count']} errors")
            print(f"    first: {info['first_error'][:200]}")

    # Exit with non-zero if pass rate < 99%
    if pct < 99.0:
        sys.exit(1)


if __name__ == "__main__":
    main()
