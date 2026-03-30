# Claude Code セッションログからの Skill 実行検出

## 概要

Claude Code のセッションログ（JSONL）から Skill（スラッシュコマンド）の実行を検出する方法をまとめる。
Skill の呼び出し経路は3パターンあり、それぞれログ構造が異なる。

---

## ログの保存場所

### 親セッション

```
~/.claude/projects/{project-dir-encoded}/{session-uuid}.jsonl
```

### サブエージェント

```
~/.claude/projects/{project-dir-encoded}/{session-uuid}/subagents/agent-{agent-id}.jsonl
~/.claude/projects/{project-dir-encoded}/{session-uuid}/subagents/agent-{agent-id}.meta.json
```

`.meta.json` にはエージェントの種別と説明が含まれる:

```json
{"agentType": "general-purpose", "description": "サブエージェントからskill-test実行"}
```

---

## Skill 実行の3パターン

### Pattern 1: 直接スラッシュコマンド

ユーザーがプロンプトに `/skill-name` や `/skill-name args` を直接入力した場合。

**ログ構造（2行で1セット）:**

```jsonl
{"type":"user","message":{"role":"user","content":"<command-message>skill-test</command-message>\n<command-name>/skill-test</command-name>"}}
{"type":"user","isMeta":true,"message":{"role":"user","content":[{"type":"text","text":"Base directory for this skill: ..."}]}}
```

引数付きの場合（例: `/head go.mod`）:

```jsonl
{"type":"user","message":{"role":"user","content":"<command-message>head</command-message>\n<command-name>/head</command-name>\n<command-args>go.mod</command-args>"}}
{"type":"user","isMeta":true,"message":{"role":"user","content":[{"type":"text","text":"# コマンド説明\n...\nARGUMENTS: go.mod"}]}}
```

**検出方法:**

1. `type: "user"` で `message.content`（文字列）に `<command-name>/X</command-name>` が含まれるメッセージを検出
2. 直後に `isMeta: true` の `type: "user"` メッセージが来ることで Skill と確定

**注意: ビルトインコマンドとの区別**

`/agents`, `/help` 等のビルトイン CLI コマンドも `<command-name>` タグを使う。
ビルトインコマンドにも `<command-args>` が付くため、タグの有無では区別できない。

```
ビルトイン: <command-name>/agents</command-name> ... <command-args></command-args>
スキル:     <command-message>head</command-message> ... <command-args>go.mod</command-args>
```

**区別方法:** ビルトインコマンドの後には `isMeta: true` のスキル展開メッセージが来ない。
`<command-name>` 検出後、次のメッセージが `isMeta: true` かどうかで判定する。

**取得可能な情報:**

| 情報 | 取得元 |
|------|--------|
| スキル名 | `<command-name>/X</command-name>` の X |
| 成否 | 常に成功（スキルが見つかり展開されたことを意味する） |
| リポジトリ | `cwd` フィールドのディレクトリ末尾 |
| ブランチ | `gitBranch` フィールド |
| 実行日時 | `timestamp` フィールド |

---

### Pattern 2: 暗黙的 Skill ツール呼び出し（親セッション）

Claude が自動的に Skill ツールを選択して呼び出した場合。
ユーザーが「skill-test を実行して」のように依頼すると発生する。

**ログ構造:**

```jsonl
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_abc","name":"Skill","input":{"skill":"skill-test"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_abc","content":"Launching skill: skill-test"}]},"toolUseResult":{"success":true,"commandName":"skill-test"}}
{"type":"user","isMeta":true,"message":{"content":[{"type":"text","text":"Base directory for this skill: ..."}]}}
```

**検出方法:**

`type: "user"` の `toolUseResult` フィールドに `commandName` が存在するかを確認する。

**取得可能な情報:**

| 情報 | 取得元 |
|------|--------|
| スキル名 | `toolUseResult.commandName` |
| 成否 | `toolUseResult.success` |
| リポジトリ | `cwd` フィールドのディレクトリ末尾 |
| ブランチ | `gitBranch` フィールド |
| 実行日時 | `timestamp` フィールド |

`assistant` メッセージの `tool_use` を見る必要はない。`user` メッセージの `toolUseResult` だけで完結する。

---

### Pattern 3: サブエージェント内での Skill 呼び出し

サブエージェント（Agent ツール）内で Skill が呼び出された場合。
**親セッションログには Skill の情報は記録されない。** サブエージェントのログを別途解析する必要がある。

**親セッションログに記録される内容:**

```jsonl
{"type":"user","toolUseResult":{"status":"completed","agentId":"a6fd2d96e2de47326","totalToolUseCount":2}}
```

`commandName` や `success` は含まれない。`ToolUseResultAgent` 形式。

**サブエージェントログの構造:**

```jsonl
{"type":"assistant","message":{"content":[{"type":"tool_use","id":"toolu_xyz","name":"Skill","input":{"skill":"skill-test"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_xyz","content":"Launching skill: skill-test"}]}}
{"type":"user","isMeta":true,"message":{"content":[{"type":"text","text":"Base directory for this skill: ..."}]}}
```

**親セッションとの違い:**

- `toolUseResult` フィールドが**存在しない**
- `assistant` の `tool_use` (name=Skill) → `user` の `tool_result` ペアでのみ検出可能

**検出方法:**

1. `type: "assistant"` で `tool_use` の `name: "Skill"` を検出し、`id` と `input.skill` を保持
2. `type: "user"` で `tool_result` の `tool_use_id` が保持した `id` と一致したら確定

**取得可能な情報:**

| 情報 | 取得元 |
|------|--------|
| スキル名 | assistant の `tool_use.input.skill` |
| 成否 | `tool_result` の `is_error` フィールド（省略時は成功） |
| リポジトリ | `cwd` フィールドのディレクトリ末尾 |
| ブランチ | `gitBranch` フィールド |
| 実行日時 | assistant メッセージの `timestamp` |

---

## パターン別の比較

| | Pattern 1 | Pattern 2 | Pattern 3 |
|---|---|---|---|
| 呼び出し方 | `/skill-name` 直接入力 | Claude が Skill ツールを選択 | サブエージェント内 |
| ログ場所 | 親セッション | 親セッション | サブエージェント |
| 検出キー | `<command-name>` + `isMeta` | `toolUseResult.commandName` | `tool_use`→`tool_result` ペア |
| 成否の取得 | 常に成功 | `toolUseResult.success` | `is_error` フィールド |
| assistant 解析 | 不要 | 不要 | 必要 |

---

## 実装

`internal/claude/sessionlog.go` の `SkillExtractor` が上記3パターンを統一的に処理する。

```go
ext := claude.NewSkillExtractor()

// JSONL の各行を順次処理
for _, line := range lines {
    usages, err := ext.Process(line)
    // usages に検出された SkillUsage が返る
}
```

サブエージェントログを解析する場合は、同じ `SkillExtractor` のインスタンスでサブエージェントの JSONL を処理する。

---

## 関連ファイル

- `docs/claude/claude-code-session-log-spec.md` — セッションログ全体の仕様書
- `docs/claude/schemas/session-log-message.schema.json` — JSON Schema
- `internal/claude/sessionlog.go` — SkillExtractor 実装
- `internal/claude/sessionlog_test.go` — テスト
- `internal/telemetry/metrics.go` — Prometheus メトリクス (`aiotel_skill_usage_total`)
