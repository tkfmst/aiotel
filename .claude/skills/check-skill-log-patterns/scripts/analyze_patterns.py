#!/usr/bin/env python3
"""Analyze Claude Code session logs for Skill execution patterns.

Scans session logs and classifies Skill-related entries into known patterns,
reporting any unclassified entries that may indicate log format changes.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
COMMAND_NAME_RE = re.compile(r"<command-name>/([^<]+)</command-name>")

# Known fields per pattern for detecting new additions
KNOWN_DIRECT_COMMAND_FIELDS = {
    "type", "uuid", "parentUuid", "isSidechain", "message", "timestamp",
    "sessionId", "userType", "entrypoint", "cwd", "version", "gitBranch",
    "slug", "promptId", "permissionMode", "agentId",
}

KNOWN_TOOL_USE_RESULT_SKILL_FIELDS = {
    "type", "uuid", "parentUuid", "isSidechain", "message", "timestamp",
    "sessionId", "userType", "entrypoint", "cwd", "version", "gitBranch",
    "slug", "promptId", "toolUseResult", "sourceToolAssistantUUID",
    "sourceToolUseID",
}

KNOWN_TOOL_USE_RESULT_SKILL_INNER_FIELDS = {
    "success", "commandName", "allowedTools",
}

KNOWN_SUBAGENT_ASSISTANT_FIELDS = {
    "type", "uuid", "parentUuid", "isSidechain", "message", "timestamp",
    "sessionId", "requestId", "userType", "entrypoint", "cwd", "version",
    "gitBranch", "slug", "agentId",
}


class PatternMatch:
    def __init__(self, pattern_name, record, source_file, skill_name=None):
        self.pattern_name = pattern_name
        self.record = record
        self.source_file = source_file
        self.skill_name = skill_name


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Scan logs from last N days (default: 7)")
    parser.add_argument("--session", type=str, help="Analyze a specific session ID only")
    parser.add_argument("--include-subagents", action="store_true", help="Also scan subagent logs")
    parser.add_argument("--stdin", action="store_true", help="Read JSONL from stdin (e.g. piped from run_and_dump.sh)")
    parser.add_argument("--verbose", action="store_true", help="Print raw JSON for each entry")
    return parser.parse_args()


def find_session_files(days, session_id=None):
    """Find .jsonl session files modified within the given timeframe."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    files = []
    if not PROJECTS_DIR.exists():
        return files

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.glob("*.jsonl"):
            if session_id and f.stem != session_id:
                continue
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                files.append(f)
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def find_subagent_files(session_files):
    """Find subagent .jsonl files for the given session files."""
    files = []
    for sf in session_files:
        subagent_dir = sf.parent / sf.stem / "subagents"
        if subagent_dir.is_dir():
            files.extend(sorted(subagent_dir.glob("*.jsonl")))
    return files


def is_skill_related(record):
    """Check if a record is related to Skill execution."""
    t = record.get("type", "")

    if t == "user":
        msg = record.get("message", {})
        content = msg.get("content", "")

        # Direct command tag
        if isinstance(content, str) and "<command-name>/" in content:
            return True

        # isMeta follow-up (potential skill expansion)
        if record.get("isMeta"):
            return True

        # toolUseResult with commandName
        tur = record.get("toolUseResult")
        if isinstance(tur, dict) and "commandName" in tur:
            return True

        # tool_result for Skill tool
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_result":
                    c = block.get("content", "")
                    if isinstance(c, str) and c.startswith("Launching skill:"):
                        return True
        return False

    if t == "assistant":
        msg = record.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    return True
        return False

    return False


def classify_record(record, prev_record=None):
    """Classify a Skill-related record into a known pattern or 'unknown'."""
    t = record.get("type", "")

    if t == "user":
        msg = record.get("message", {})
        content = msg.get("content", "")

        # Pattern 1 - Line A: direct command tag
        if isinstance(content, str) and "<command-name>/" in content:
            m = COMMAND_NAME_RE.search(content)
            skill = m.group(1) if m else "?"
            return "pattern1_command", skill

        # Pattern 1 - Line B: isMeta confirmation
        if record.get("isMeta") and prev_record:
            prev_msg = prev_record.get("message", {})
            prev_content = prev_msg.get("content", "")
            if isinstance(prev_content, str) and "<command-name>/" in prev_content:
                m = COMMAND_NAME_RE.search(prev_content)
                skill = m.group(1) if m else "?"
                return "pattern1_meta", skill

        # Pattern 2: toolUseResult.commandName
        tur = record.get("toolUseResult")
        if isinstance(tur, dict) and "commandName" in tur:
            return "pattern2_toolUseResult", tur["commandName"]

        # Subagent tool_result (Launching skill:)
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_result":
                    c = block.get("content", "")
                    if isinstance(c, str) and c.startswith("Launching skill:"):
                        skill = c.replace("Launching skill:", "").strip()
                        return "pattern3_tool_result", skill

        # isMeta without matching prev (e.g. subagent skill expansion)
        if record.get("isMeta"):
            return "meta_unmatched", None

    if t == "assistant":
        msg = record.get("message", {})
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    inp = block.get("input", {})
                    skill = inp.get("skill", "?")
                    return "pattern3_tool_use", skill

    return "unknown", None


def detect_new_fields(record, classification):
    """Detect fields not in the known set for the given classification."""
    new_fields = []

    if classification == "pattern1_command":
        extra = set(record.keys()) - KNOWN_DIRECT_COMMAND_FIELDS
        for f in extra:
            new_fields.append(f"record.{f}")

    elif classification == "pattern2_toolUseResult":
        extra = set(record.keys()) - KNOWN_TOOL_USE_RESULT_SKILL_FIELDS
        for f in extra:
            new_fields.append(f"record.{f}")
        tur = record.get("toolUseResult", {})
        if isinstance(tur, dict):
            inner_extra = set(tur.keys()) - KNOWN_TOOL_USE_RESULT_SKILL_INNER_FIELDS
            for f in inner_extra:
                new_fields.append(f"toolUseResult.{f}")

    elif classification == "pattern3_tool_use":
        extra = set(record.keys()) - KNOWN_SUBAGENT_ASSISTANT_FIELDS
        for f in extra:
            new_fields.append(f"record.{f}")

    return new_fields


def analyze_file(filepath, verbose=False):
    """Analyze a single JSONL file and return classified entries."""
    results = []
    prev_record = None

    with open(filepath) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not is_skill_related(record):
                prev_record = record
                continue

            classification, skill_name = classify_record(record, prev_record)
            new_fields = detect_new_fields(record, classification)

            results.append({
                "file": str(filepath),
                "line": line_num,
                "classification": classification,
                "skill_name": skill_name,
                "new_fields": new_fields,
                "timestamp": record.get("timestamp", ""),
                "version": record.get("version", ""),
                "raw": record if verbose else None,
            })

            prev_record = record

    return results


def print_report(all_results):
    """Print a summary report of the analysis."""
    if not all_results:
        print("Skill 関連のログエントリが見つかりませんでした。")
        return

    # Count by classification
    counts = defaultdict(int)
    skills = defaultdict(set)
    new_fields_all = defaultdict(set)
    unknowns = []
    versions = set()

    for r in all_results:
        c = r["classification"]
        counts[c] += 1
        if r["skill_name"]:
            skills[c].add(r["skill_name"])
        for f in r["new_fields"]:
            new_fields_all[c].add(f)
        if c == "unknown":
            unknowns.append(r)
        if r["version"]:
            versions.add(r["version"])

    print("=" * 60)
    print("Skill ログパターン解析レポート")
    print("=" * 60)
    print(f"\n対象エントリ数: {len(all_results)}")
    print(f"Claude Code バージョン: {', '.join(sorted(versions)) or 'N/A'}")

    # Pattern summary
    pattern_labels = {
        "pattern1_command": "Pattern 1 - 直接コマンド (command-name タグ)",
        "pattern1_meta": "Pattern 1 - 直接コマンド (isMeta 確認)",
        "pattern2_toolUseResult": "Pattern 2 - 暗黙的 Skill (toolUseResult)",
        "pattern3_tool_use": "Pattern 3 - サブエージェント (assistant tool_use)",
        "pattern3_tool_result": "Pattern 3 - サブエージェント (user tool_result)",
        "meta_unmatched": "isMeta (スキル展開、前行マッチなし)",
        "unknown": "未分類",
    }

    print("\n--- パターン別件数 ---")
    for key, label in pattern_labels.items():
        if counts[key] > 0:
            skill_list = ", ".join(sorted(skills[key])) if skills[key] else ""
            print(f"  {label}: {counts[key]}件")
            if skill_list:
                print(f"    スキル: {skill_list}")

    # New fields
    has_new = any(new_fields_all.values())
    if has_new:
        print("\n--- 新規フィールド検出 ---")
        for c, fields in new_fields_all.items():
            if fields:
                label = pattern_labels.get(c, c)
                print(f"  [{label}]")
                for f in sorted(fields):
                    print(f"    - {f}")
    else:
        print("\n新規フィールド: なし")

    # Unknown entries
    if unknowns:
        print(f"\n--- 未分類エントリ ({len(unknowns)}件) ---")
        for u in unknowns[:5]:
            print(f"  File: {u['file']}:{u['line']}")
            print(f"  Timestamp: {u['timestamp']}")
            if u["raw"]:
                print(f"  Raw: {json.dumps(u['raw'], ensure_ascii=False)[:300]}")
            print()
        if len(unknowns) > 5:
            print(f"  ... 他 {len(unknowns) - 5} 件")
    else:
        print("\n未分類エントリ: なし")

    print("\n" + "=" * 60)

    # Verbose output
    verbose_entries = [r for r in all_results if r["raw"]]
    if verbose_entries:
        print("\n--- 全エントリ詳細 ---")
        for r in verbose_entries:
            print(f"\n[{r['classification']}] {r['file']}:{r['line']}")
            print(json.dumps(r["raw"], ensure_ascii=False, indent=2))


def analyze_stdin(verbose=False):
    """Analyze JSONL from stdin."""
    results = []
    prev_record = None

    for line_num, line in enumerate(sys.stdin, 1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not is_skill_related(record):
            prev_record = record
            continue

        classification, skill_name = classify_record(record, prev_record)
        new_fields = detect_new_fields(record, classification)

        results.append({
            "file": "<stdin>",
            "line": line_num,
            "classification": classification,
            "skill_name": skill_name,
            "new_fields": new_fields,
            "timestamp": record.get("timestamp", ""),
            "version": record.get("version", ""),
            "raw": record if verbose else None,
        })

        prev_record = record

    return results


def main():
    args = parse_args()

    if args.stdin:
        all_results = analyze_stdin(verbose=args.verbose)
        print_report(all_results)
        return

    session_files = find_session_files(args.days, args.session)
    if not session_files:
        print(f"直近 {args.days} 日間のセッションログが見つかりませんでした。", file=sys.stderr)
        sys.exit(1)

    print(f"セッションファイル: {len(session_files)} 件を解析中...")

    all_results = []
    for sf in session_files:
        all_results.extend(analyze_file(sf, verbose=args.verbose))

    if args.include_subagents:
        subagent_files = find_subagent_files(session_files)
        if subagent_files:
            print(f"サブエージェントファイル: {len(subagent_files)} 件を解析中...")
            for sf in subagent_files:
                all_results.extend(analyze_file(sf, verbose=args.verbose))

    print_report(all_results)


if __name__ == "__main__":
    main()
