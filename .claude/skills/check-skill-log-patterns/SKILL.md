---
name: check-skill-log-patterns
description: >
  セッションログ内の Skill 実行パターンを解析・検証するスキル。
  ログフォーマットの変更検出、新パターンの発見、既知パターンとの差分確認に使う。
  「ログパターン確認」「skill ログチェック」「ログ構造が変わったか確認」
  「セッションログのスキル実行を調べて」と言われたら使う。
---

# Skill ログパターン検証

## 概要

Claude Code のセッションログに記録される Skill 実行パターンを検証する。
ログフォーマットは Claude Code のバージョンアップで変わる可能性があるため、
`claude -p` でスキルを実行してログを生成し、既知パターンと照合する。

## ツール構成

```
scripts/
├── run_and_dump.sh       # claude -p でスキルを実行し、セッションログを出力
└── analyze_patterns.py   # ログを分類して差分レポートを生成
```

## 使い方

スキルディレクトリ: `.claude/skills/check-skill-log-patterns`

### 1. スキルを実行してログを出力

```bash
# /skill-test を実行し、生成されたセッションログを全行出力
./scripts/run_and_dump.sh /skill-test

# skill関連のエントリのみ出力
./scripts/run_and_dump.sh -s /skill-test

# 引数付きスキル
./scripts/run_and_dump.sh -s /head go.mod

# raw JSONL で出力（jq等にパイプしやすい）
./scripts/run_and_dump.sh -r -s /skill-test
```

### 2. パイプで解析

```bash
# 実行 → 抽出 → 解析を一発で
./scripts/run_and_dump.sh -r /skill-test | python3 scripts/analyze_patterns.py --stdin

# skill関連のみ抽出して解析
./scripts/run_and_dump.sh -r -s /skill-test | python3 scripts/analyze_patterns.py --stdin
```

### 3. 既存ログを解析（実行せずに）

```bash
# 直近7日のログを解析
python3 scripts/analyze_patterns.py

# 直近1日、サブエージェント含む
python3 scripts/analyze_patterns.py --days 1 --include-subagents

# 特定セッション
python3 scripts/analyze_patterns.py --session SESSION_UUID

# 生JSON付きで詳細出力
python3 scripts/analyze_patterns.py --days 1 --verbose
```

### 4. ログを直接確認（jq）

```bash
# run_and_dump.sh の出力を jq で整形
./scripts/run_and_dump.sh -r -s /skill-test | jq .

# 特定フィールドだけ抽出
./scripts/run_and_dump.sh -r -s /skill-test | jq '{type, isMeta, toolUseResult}'
```

## 解析レポートの読み方

`analyze_patterns.py` は以下を報告する:

- **パターン別件数** — 3パターン（直接コマンド / toolUseResult / サブエージェント）ごとの検出数
- **新規フィールド** — 既知のフィールドセットにないフィールドが検出された場合に表示
- **未分類エントリ** — 既知パターンに当てはまらない Skill 関連ログ

### 期待される正常状態

```
新規フィールド: なし
未分類エントリ: なし
```

### 要対応

- **新規フィールド検出**: スキーマ（`docs/claude/schemas/`）と既知フィールドセット（`analyze_patterns.py`）を更新
- **未分類エントリ**: 新パターンの可能性。`--verbose` で生ログを確認し、`docs/claude/README.md` とGoコード（`internal/claude/sessionlog.go`）を更新

## 既知の3パターン

詳細は `docs/claude/README.md` を参照。

| Pattern | 発生条件 | 検出キー |
|---------|---------|---------|
| 1: 直接コマンド | `/skill-name` 入力 | `<command-name>` + 次行 `isMeta: true` |
| 2: 暗黙的 Skill | Claude が Skill ツールを選択 | `toolUseResult.commandName` |
| 3: サブエージェント | Agent 内で Skill 呼び出し | assistant `tool_use` → user `tool_result` ペア |
