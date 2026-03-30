#!/usr/bin/env bash
# Run a skill via `claude -p` and dump the resulting session log.
#
# Usage:
#   ./run_and_dump.sh /skill-test
#   ./run_and_dump.sh /head go.mod
#   ./run_and_dump.sh -r -s /skill-test | python3 scripts/analyze_patterns.py --stdin
#
# Options:
#   -r, --raw         Output raw JSONL (default: pretty-printed JSON)
#   -s, --skill-only  Filter to skill-related entries only

set -eo pipefail

PROJECTS_DIR="${HOME}/.claude/projects"

# --- parse args ---
RAW=false
SKILL_ONLY=false
SKILL_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--raw)        RAW=true; shift ;;
    -s|--skill-only) SKILL_ONLY=true; shift ;;
    *)               SKILL_ARGS+=("$1"); shift ;;
  esac
done

if [[ ${#SKILL_ARGS[@]} -eq 0 ]]; then
  echo "Usage: $0 [options] /skill-name [args...]" >&2
  echo "" >&2
  echo "Examples:" >&2
  echo "  $0 /skill-test" >&2
  echo "  $0 -s /skill-test              # skill関連エントリのみ" >&2
  echo "  $0 -r -s /skill-test | jq .    # raw JSONL をjqで整形" >&2
  echo "  $0 -r /skill-test | python3 scripts/analyze_patterns.py --stdin" >&2
  exit 1
fi

PROMPT="${SKILL_ARGS[*]}"
PROJECT_DIR="$(pwd)"

# Claude Code encodes project dir: replace / and . with -
PROJECT_ENCODED=$(echo "$PROJECT_DIR" | sed 's|[/.]|-|g')
SESSION_DIR="${PROJECTS_DIR}/${PROJECT_ENCODED}"

# Record timestamp before running
BEFORE_TS=$(date +%s)

# Disable MCP servers via empty config file to avoid latency
MCP_EMPTY=$(mktemp)
echo '{"mcpServers":{}}' > "$MCP_EMPTY"
trap "rm -f '$MCP_EMPTY'" EXIT

echo "Running: claude -p \"${PROMPT}\" (MCP disabled)" >&2
cd "$PROJECT_DIR"
claude -p --strict-mcp-config --mcp-config "$MCP_EMPTY" -- "$PROMPT" >/dev/null 2>&1 || true

# Wait for filesystem to settle
sleep 1

# Find the newest session log created after BEFORE_TS
NEWEST_LOG=$(python3 -c "
import os, sys
session_dir = sys.argv[1]
before_ts = int(sys.argv[2])
best_file, best_mtime = '', 0
if os.path.isdir(session_dir):
    for f in os.listdir(session_dir):
        if not f.endswith('.jsonl'):
            continue
        path = os.path.join(session_dir, f)
        mtime = int(os.path.getmtime(path))
        if mtime >= before_ts and mtime > best_mtime:
            best_file, best_mtime = path, mtime
print(best_file)
" "$SESSION_DIR" "$BEFORE_TS")

if [[ -z "$NEWEST_LOG" ]]; then
  echo "Error: No session log found after execution." >&2
  echo "Looked in: ${SESSION_DIR}" >&2
  exit 1
fi

SESSION_ID=$(basename "$NEWEST_LOG" .jsonl)
echo "Session: ${SESSION_ID}" >&2
echo "Log: ${NEWEST_LOG}" >&2

# Check for subagent logs
SUBAGENT_DIR="${SESSION_DIR}/${SESSION_ID}/subagents"
if [[ -d "$SUBAGENT_DIR" ]]; then
  SUBAGENT_COUNT=$(find "$SUBAGENT_DIR" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$SUBAGENT_COUNT" -gt 0 ]]; then
    echo "Subagent logs: ${SUBAGENT_COUNT} files" >&2
  fi
fi

echo "---" >&2

# --- output functions ---
dump_raw() {
  cat "$1"
}

dump_pretty() {
  python3 -c "
import sys, json
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    try:
        print(json.dumps(json.loads(line), ensure_ascii=False, indent=2))
    except: print(line)
" "$1"
}

dump_skill_only_raw() {
  python3 -c "
import sys, json, re
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    try:
        r = json.loads(line)
    except: continue
    t = r.get('type','')
    if t == 'user':
        msg = r.get('message',{})
        c = msg.get('content','')
        if isinstance(c, str) and '<command-name>/' in c: pass
        elif r.get('isMeta'): pass
        elif isinstance(r.get('toolUseResult'), dict) and 'commandName' in r.get('toolUseResult',{}): pass
        elif isinstance(c, list) and any(isinstance(b.get('content',''), str) and b['content'].startswith('Launching skill:') for b in c if isinstance(b, dict)): pass
        else: continue
    elif t == 'assistant':
        cc = r.get('message',{}).get('content',[])
        if not (isinstance(cc, list) and any(b.get('type')=='tool_use' and b.get('name')=='Skill' for b in cc if isinstance(b, dict))): continue
    else: continue
    print(line if sys.argv[2] == 'raw' else json.dumps(r, ensure_ascii=False, indent=2))
" "$1" "$2"
}

# --- dump ---
dump_file() {
  local file="$1"
  if [[ "$SKILL_ONLY" == true ]]; then
    local mode="pretty"
    [[ "$RAW" == true ]] && mode="raw"
    dump_skill_only_raw "$file" "$mode"
  elif [[ "$RAW" == true ]]; then
    dump_raw "$file"
  else
    dump_pretty "$file"
  fi
}

echo "=== Parent session ===" >&2
dump_file "$NEWEST_LOG"

if [[ -d "$SUBAGENT_DIR" ]]; then
  for sa in "$SUBAGENT_DIR"/*.jsonl; do
    [[ -f "$sa" ]] || continue
    echo "" >&2
    echo "=== Subagent: $(basename "$sa" .jsonl) ===" >&2
    META="${sa%.jsonl}.meta.json"
    if [[ -f "$META" ]]; then
      echo "Meta: $(cat "$META")" >&2
    fi
    dump_file "$sa"
  done
fi
