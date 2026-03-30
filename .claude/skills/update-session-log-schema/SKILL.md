---
name: update-session-log-schema
description: >
  Claude Code セッションログの仕様書と JSON Schema を分析・更新するスキル。
  `~/.claude/projects/` 配下のセッションログ (.jsonl) を解析し、
  新しいメッセージタイプやフィールドを検出して docs/claude/ 配下のドキュメントを更新する。
  期間指定で対象ログを絞り込み可能（デフォルト: 直近5日）。
  「ログスキーマ更新」「セッションログ仕様更新」「schema update」と言われたら使う。
  ログ構造の変更検出やスキーマのバリデーション精度向上にも使える。
---

# Claude Code セッションログ仕様・スキーマ更新スキル

## 概要

`~/.claude/projects/` 配下のセッションログを解析し、以下の成果物を生成・更新する:

1. **仕様書** (`docs/claude/claude-code-session-log-spec.md`)
2. **セッションログ JSON Schema** (`docs/claude/schemas/session-log-message.schema.json`)
3. **セッションインデックス JSON Schema** (`docs/claude/schemas/sessions-index.schema.json`)

## 引数

| 引数 | 説明 | デフォルト |
|------|------|-----------|
| `--days N` | 直近N日のログのみ対象 | `5` |
| `--since YYYY-MM-DD` | 指定日以降のログを対象 | なし |
| `--until YYYY-MM-DD` | 指定日までのログを対象 | なし |
| `--full` | 全ログを対象（期間制限なし） | `false` |
| `--validate-only` | スキーマ更新せずバリデーションのみ実行 | `false` |

例:
- `/update-session-log-schema` → 直近5日
- `/update-session-log-schema --days 14` → 直近14日
- `/update-session-log-schema --since 2026-03-01 --until 2026-03-15`
- `/update-session-log-schema --full` → 全期間
- `/update-session-log-schema --validate-only` → バリデーションのみ

## 手順

### Step 1: ログ収集と期間フィルタリング

`scripts/collect_log_types.py` を使って対象期間のログを解析する。

```bash
python3 <skill-dir>/scripts/collect_log_types.py ~/.claude/projects --days <N>
```

このスクリプトは以下を出力する:
- 全メッセージタイプとそのフィールド一覧
- system の subtype バリエーション
- progress の data.type バリエーション
- toolUseResult のキー組み合わせ
- 各フィールドの型情報とサンプル値

### Step 2: 差分検出

Step 1 の出力と、既存の `docs/claude/schemas/session-log-message.schema.json` を比較して以下を検出する:

1. **新しいメッセージタイプ** — スキーマの `oneOf` に存在しない `type` 値
2. **新しいフィールド** — 既存タイプに追加されたフィールド
3. **新しい enum 値** — `subtype`, `data.type`, `operation` 等の新しい値
4. **型の変更** — フィールドの型が変わったケース（例: string → string|null）

差分がなければ「変更なし」と報告して終了。

### Step 3: スキーマ更新

差分に基づいて JSON Schema を更新する。更新時のルール:

- 新メッセージタイプ → `$defs` に定義を追加し、トップレベルの `oneOf` に `$ref` を追加
- 新フィールド → 該当する定義の `properties` に追加
- 新 enum 値 → `enum` 配列に追加
- 型の拡張 → `type: "string"` を `type: ["string", "null"]` のように拡張
- `required` は実データで全メッセージに存在するフィールドのみ指定
- `anyOf` はツール結果など複数スキーマにマッチしうるケースで使用

### Step 4: バリデーション

更新後のスキーマで対象期間のログを検証する。

```bash
python3 <skill-dir>/scripts/validate_schema.py \
  docs/claude/schemas/session-log-message.schema.json \
  ~/.claude/projects \
  --days <N>
```

出力:
- Pass / Fail 件数と Pass rate
- エラー種別ごとの件数と最初のエラーメッセージ

**目標: 99% 以上の Pass rate**

Pass rate が 99% 未満の場合はエラーを分析して修正を繰り返す。

### Step 5: 仕様書更新

スキーマの差分に基づいて `docs/claude/claude-code-session-log-spec.md` を更新する:

- 新メッセージタイプ → 対応するセクションを追加
- 新フィールド → 既存テーブルに行を追加
- 新 subtype/data.type → 一覧テーブルと詳細セクションを追加
- セクション3「ログから取得・分析可能な情報」に該当する分析項目があれば追加

### Step 6: 結果報告

最終的に以下を報告する:

```
## 更新結果

- 対象期間: YYYY-MM-DD 〜 YYYY-MM-DD
- 対象ログ: X files, Y messages
- 検出された変更:
  - 新メッセージタイプ: [リスト]
  - 新フィールド: [リスト]
  - 新 enum 値: [リスト]
- バリデーション: Pass X / Fail Y (XX.X%)
- 更新ファイル:
  - docs/claude/schemas/session-log-message.schema.json
  - docs/claude/schemas/sessions-index.schema.json
  - docs/claude/claude-code-session-log-spec.md
```

## 注意事項

- ログには機密情報（ファイル内容、コマンド出力）が含まれる可能性がある。スキーマ定義にサンプル値を含めない
- `<synthetic>` モデルのメッセージや、`callback` タイプの hookInfos など edge case に注意
- `toolUseResult` は文字列型の場合もある（MCP結果等）
- `sessions-index.json` は一部プロジェクトにのみ存在する
