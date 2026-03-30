#!/usr/bin/env python3
"""Claude Code セッションログを解析し、メッセージタイプ・フィールド構造を収集する。

Usage:
    python3 collect_log_types.py ~/.claude/projects [--days N] [--since DATE] [--until DATE] [--full]
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone


def parse_args():
    parser = argparse.ArgumentParser(description="Collect message types and fields from Claude Code session logs")
    parser.add_argument("base_dir", help="Base directory (e.g., ~/.claude/projects)")
    parser.add_argument("--days", type=int, default=5, help="Only check logs modified within N days (default: 5)")
    parser.add_argument("--since", type=str, help="Only check logs since this date (YYYY-MM-DD)")
    parser.add_argument("--until", type=str, help="Only check logs until this date (YYYY-MM-DD)")
    parser.add_argument("--full", action="store_true", help="Check all logs (no date filter)")
    return parser.parse_args()


def get_date_range(args):
    """Return (since_ts, until_ts) as Unix timestamps, or (None, None) for --full."""
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
    """Collect .jsonl files within the date range based on file mtime."""
    pattern = os.path.join(base_dir, "*", "*.jsonl")
    files = glob.glob(pattern)

    if since_ts is None:
        return files

    filtered = []
    for f in files:
        mtime = os.path.getmtime(f)
        if since_ts <= mtime <= until_ts:
            filtered.append(f)
    return filtered


def analyze_files(files):
    """Analyze all JSONL files and collect type/field information."""
    type_fields = {}
    system_subtypes = set()
    progress_data_types = set()
    tooluse_result_combos = set()

    total_messages = 0

    for fpath in files:
        with open(fpath) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                total_messages += 1
                t = obj.get("type", "unknown")

                if t not in type_fields:
                    type_fields[t] = {}

                for k, v in obj.items():
                    if k not in type_fields[t]:
                        type_fields[t][k] = {"types": set(), "count": 0, "sample": None}
                    vtype = type(v).__name__ if v is not None else "null"
                    type_fields[t][k]["types"].add(vtype)
                    type_fields[t][k]["count"] += 1
                    if type_fields[t][k]["sample"] is None and v is not None:
                        s = json.dumps(v, ensure_ascii=False)
                        if len(s) > 120:
                            s = s[:120] + "..."
                        type_fields[t][k]["sample"] = s

                if t == "system":
                    system_subtypes.add(obj.get("subtype", "unknown"))

                if t == "progress":
                    d = obj.get("data", {})
                    if isinstance(d, dict):
                        progress_data_types.add(d.get("type", "unknown"))

                tur = obj.get("toolUseResult")
                if isinstance(tur, dict):
                    tooluse_result_combos.add(frozenset(tur.keys()))

    return {
        "total_files": len(files),
        "total_messages": total_messages,
        "type_fields": type_fields,
        "system_subtypes": sorted(system_subtypes),
        "progress_data_types": sorted(progress_data_types),
        "tooluse_result_combos": [sorted(c) for c in sorted(tooluse_result_combos, key=lambda x: str(sorted(x)))],
    }


def print_report(result):
    """Print a human-readable report."""
    print(f"Files: {result['total_files']}")
    print(f"Messages: {result['total_messages']}")

    print(f"\n=== Message Types ({len(result['type_fields'])}) ===")
    for t in sorted(result["type_fields"].keys()):
        fields = result["type_fields"][t]
        count = max(f["count"] for f in fields.values()) if fields else 0
        print(f"\n--- {t} ({count} messages) ---")
        for k in sorted(fields.keys()):
            info = fields[k]
            types_str = ", ".join(sorted(info["types"]))
            print(f"  {k}: [{types_str}] (count={info['count']})")

    print(f"\n=== System Subtypes: {result['system_subtypes']} ===")
    print(f"\n=== Progress data.types: {result['progress_data_types']} ===")

    print(f"\n=== ToolUseResult Key Combos ({len(result['tooluse_result_combos'])}) ===")
    for combo in result["tooluse_result_combos"]:
        print(f"  {combo}")


def print_json(result):
    """Print JSON output for programmatic use."""
    # Convert sets to lists for JSON serialization
    serializable = {
        "total_files": result["total_files"],
        "total_messages": result["total_messages"],
        "message_types": sorted(result["type_fields"].keys()),
        "system_subtypes": result["system_subtypes"],
        "progress_data_types": result["progress_data_types"],
        "tooluse_result_key_combos": result["tooluse_result_combos"],
        "fields_by_type": {},
    }
    for t, fields in result["type_fields"].items():
        serializable["fields_by_type"][t] = {}
        for k, info in fields.items():
            serializable["fields_by_type"][t][k] = {
                "types": sorted(info["types"]),
                "count": info["count"],
                "sample": info["sample"],
            }

    json.dump(serializable, sys.stdout, indent=2, ensure_ascii=False)
    print()


def main():
    args = parse_args()
    base_dir = os.path.expanduser(args.base_dir)
    since_ts, until_ts = get_date_range(args)

    files = collect_files(base_dir, since_ts, until_ts)
    if not files:
        print("No log files found in the specified date range.", file=sys.stderr)
        sys.exit(1)

    result = analyze_files(files)
    print_report(result)


if __name__ == "__main__":
    main()
