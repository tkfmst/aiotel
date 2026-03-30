# Claude Code セッションログ仕様書

## 概要

`~/.claude/projects/` 配下には、Claude Code の全セッション（会話）の完全なログが JSONL 形式で保存されている。
このドキュメントでは、ログから取得可能な情報を網羅的にまとめる。

---

## ディレクトリ構造

```
~/.claude/projects/
├── {project-dir-encoded}/          # プロジェクトごとのディレクトリ
│   ├── {session-uuid}.jsonl        # セッションログ（メイン）
│   ├── sessions-index.json         # セッションインデックス（一部プロジェクトのみ）
│   └── memory/                     # プロジェクト固有メモリ
└── ...
```

### プロジェクトディレクトリの命名規則

作業ディレクトリの絶対パスの `/` を `-` に置換したもの。

例: `/path/to/repository/aiotel` → `-path-to-repository-aiotel`

worktree を使用した場合は `--claude-worktrees-{name}` が付与される。

---

## 1. セッションログ (`{session-uuid}.jsonl`)

1行1JSONオブジェクトの JSONL 形式。各行は以下の `type` フィールドで種別が決まる。

### 1.1 メッセージタイプ一覧

| type | 説明 |
|------|------|
| `file-history-snapshot` | ファイル変更履歴のスナップショット |
| `user` | ユーザーの発言・ツール実行結果 |
| `assistant` | Claude の応答（thinking、tool_use、text） |
| `system` | システムイベント（hook実行結果、ターン所要時間、APIエラー、コンテキスト圧縮、ローカルコマンド） |
| `progress` | hook/bash/agent/mcp/検索の実行中進捗情報 |
| `pr-link` | 作成されたPRへのリンク |
| `last-prompt` | セッションの最後のプロンプト |
| `agent-name` | セッションに割り当てられたエージェント名 |
| `custom-title` | セッションのカスタムタイトル |
| `queue-operation` | キュー操作（enqueue/dequeue） |

---

### 1.2 共通フィールド

ほぼ全てのメッセージに含まれるフィールド:

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `type` | string | メッセージ種別 |
| `uuid` | string | メッセージの一意ID |
| `parentUuid` | string \| null | 親メッセージのID（会話のツリー構造を構成） |
| `timestamp` | string (ISO 8601) | 発生日時 |
| `sessionId` | string | セッションの一意ID |
| `cwd` | string | コマンド実行時の作業ディレクトリ |
| `version` | string | Claude Code のバージョン（例: `2.1.81`） |
| `gitBranch` | string | 実行時の git ブランチ |
| `entrypoint` | string | 起動元（`cli`, IDE拡張など） |
| `userType` | string | ユーザー種別（`external`） |
| `isSidechain` | boolean | サイドチェーン（分岐した会話）かどうか |
| `slug` | string | セッションのスラッグ名（人間可読なID） |

---

### 1.3 `user` メッセージ

ユーザーの入力およびツール実行結果を記録。

#### 取得可能な情報

| フィールド | パス | 説明 |
|-----------|------|------|
| ユーザー入力テキスト | `message.content` (string) | ユーザーが入力した質問・指示 |
| ツール実行結果 | `message.content[].tool_use_id` | どのツール呼び出しに対する結果か |
| パーミッションモード | `permissionMode` | `default`, `bypassPermissions` など |
| プロンプトID | `promptId` | 同一ターンのプロンプトを紐づけるID |
| ツール結果詳細 | `toolUseResult` | ツール実行の詳細結果 |

#### Skill 実行時のログパターン

Skill（スラッシュコマンド）の実行は2つの方法で呼び出される。それぞれログ構造が異なる。

**パターン1: 直接スラッシュコマンド（プロンプトから `/skill-name` を入力）**

1. `user` メッセージ: `message.content` が文字列で、`<command-message>` と `<command-name>` タグを含む
   ```json
   {
     "type": "user",
     "message": {
       "role": "user",
       "content": "<command-message>skill-test</command-message>\n<command-name>/skill-test</command-name>"
     }
   }
   ```
2. `user` メッセージ: `isMeta: true` で、スキルの展開されたプロンプト内容を含む
3. `assistant` メッセージ: スキルの指示に従った応答

**パターン2: 暗黙的な Skill ツール呼び出し（Claude が自動的にスキルを選択）**

1. `assistant` メッセージ: `tool_use` で `name: "Skill"` を呼び出し
2. `user` メッセージ: `tool_result` で Skill ツールの結果を返す。`toolUseResult` フィールドに `ToolUseResultSkill` 形式の結果が含まれる
   ```json
   {
     "type": "user",
     "message": { "content": [{"type": "tool_result", "tool_use_id": "toolu_...", "content": "Launching skill: skill-test"}] },
     "toolUseResult": { "success": true, "commandName": "skill-test" }
   }
   ```
3. `user` メッセージ: `isMeta: true`、`sourceToolUseID` 付きで、スキルの展開されたプロンプト内容を含む
4. `assistant` メッセージ: スキルの指示に従った応答

#### `toolUseResult` のバリエーション

**Bash 実行結果:**
```json
{
  "stdout": "...",
  "stderr": "...",
  "interrupted": false,
  "isImage": false,
  "noOutputExpected": false
}
```

**ToolSearch 結果:**
```json
{
  "matches": ["Grep", "Agent"],
  "query": "select:Grep,Agent",
  "total_deferred_tools": 58
}
```

**Skill 実行結果:**
```json
{
  "commandName": "skill-test",
  "success": true
}
```

---

### 1.4 `assistant` メッセージ

Claude の応答を記録。1つのAPIレスポンスが複数行に分割される場合がある（streaming）。

#### 取得可能な情報

| フィールド | パス | 説明 |
|-----------|------|------|
| モデル名 | `message.model` | 使用モデル（例: `claude-opus-4-6`） |
| リクエストID | `requestId` | Anthropic APIのリクエストID |
| 停止理由 | `message.stop_reason` | `end_turn`, `tool_use`, `null`（streaming中） |
| コンテンツ種別 | `message.content[].type` | `thinking`, `tool_use`, `text` |

#### コンテンツタイプ別の取得可能情報

**`thinking` (内部思考):**
| フィールド | 説明 |
|-----------|------|
| `thinking` | Claude の思考プロセスのテキスト |
| `signature` | thinking の署名 |

**`tool_use` (ツール呼び出し):**
| フィールド | 説明 |
|-----------|------|
| `id` | ツール呼び出しID |
| `name` | ツール名（`Bash`, `Read`, `Edit`, `Grep`, `Glob`, `Agent` 等） |
| `input` | ツールへの入力パラメータ |
| `caller.type` | 呼び出し元の種別 |

**`text` (テキスト応答):**
| フィールド | 説明 |
|-----------|------|
| `text` | ユーザーに表示されるテキスト |

#### トークン使用量 (`message.usage`)

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `input_tokens` | number | 入力トークン数 |
| `output_tokens` | number | 出力トークン数 |
| `cache_creation_input_tokens` | number | キャッシュ作成に使用された入力トークン数 |
| `cache_read_input_tokens` | number | キャッシュから読み取った入力トークン数 |
| `service_tier` | string | サービスティア（`standard`） |
| `inference_geo` | string | 推論の地理的リージョン |
| `speed` | string | 速度モード（`standard`） |
| `cache_creation.ephemeral_5m_input_tokens` | number | 5分間のエフェメラルキャッシュ作成トークン |
| `cache_creation.ephemeral_1h_input_tokens` | number | 1時間のエフェメラルキャッシュ作成トークン |
| `server_tool_use.web_search_requests` | number | Web検索リクエスト数 |
| `server_tool_use.web_fetch_requests` | number | Webフェッチリクエスト数 |

---

### 1.5 `system` メッセージ

システムイベントを記録。`subtype` で種別が決まる。

#### subtype 一覧

| subtype | 説明 |
|---------|------|
| `stop_hook_summary` | Stop hook の実行結果 |
| `turn_duration` | 1ターンの所要時間 |
| `api_error` | Anthropic API のエラー（過負荷、レート制限等） |
| `compact_boundary` | コンテキスト圧縮の境界マーカー |
| `local_command` | ローカルコマンドの実行結果（voice mode 等） |

#### subtype: `turn_duration`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `durationMs` | number | 1ターン（ユーザー入力→Claude応答完了）の所要時間（ミリ秒） |
| `isMeta` | boolean | メタ情報かどうか |

#### subtype: `stop_hook_summary`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `hookCount` | number | 実行されたhook数 |
| `hookInfos` | array | 各hookの詳細 |
| `hookInfos[].command` | string | 実行されたhookコマンド |
| `hookInfos[].durationMs` | number | hook実行時間（ミリ秒） |
| `hookErrors` | array | hookのエラー情報 |
| `preventedContinuation` | boolean | hookが会話の継続を阻止したか |
| `stopReason` | string | 停止理由 |
| `hasOutput` | boolean | hookに出力があったか |
| `level` | string | ログレベル（`suggestion` 等） |

---

#### subtype: `api_error`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `error.status` | number | HTTP ステータスコード（529=過負荷等） |
| `error.error.error.type` | string | エラー種別（`overloaded_error` 等） |
| `error.error.error.message` | string | エラーメッセージ |
| `retryInMs` | number | リトライ待機時間（ミリ秒） |
| `retryAttempt` | number | リトライ回数 |
| `maxRetries` | number | 最大リトライ回数 |

#### subtype: `compact_boundary`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `content` | string | `"Conversation compacted"` 等のメッセージ |
| `logicalParentUuid` | string | コンテキスト圧縮前の論理的な親UUID |

#### subtype: `local_command`

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `content` | string | コマンドの出力（`<local-command-stdout>` タグで囲まれる） |
| `level` | string | ログレベル（`info`） |

---

### 1.6 `progress` メッセージ

各種処理の実行中進捗情報。`data.type` で進捗の種別が決まる。

#### data.type 一覧

| data.type | 説明 |
|-----------|------|
| `hook_progress` | Hook 実行進捗 |
| `bash_progress` | Bash コマンド実行進捗 |
| `agent_progress` | サブエージェント実行進捗 |
| `mcp_progress` | MCP サーバー呼び出し進捗 |
| `waiting_for_task` | タスク待機中 |
| `query_update` | Web 検索クエリ更新 |
| `search_results_received` | Web 検索結果受信 |

#### 共通フィールド

| フィールド | パス | 説明 |
|-----------|------|------|
| 対象ツールID | `toolUseID` | 対象のツール呼び出しID |
| 親ツールID | `parentToolUseID` | 親のツール呼び出しID |

#### data.type: `hook_progress`

| フィールド | パス | 説明 |
|-----------|------|------|
| hookイベント種別 | `data.hookEvent` | `Stop`, `PostToolUse` など |
| hook名 | `data.hookName` | `Stop`, `PostToolUse:Read`, `PostToolUse:Edit` など |
| 実行コマンド | `data.command` | hook のコマンドパス |

#### data.type: `bash_progress`

| フィールド | パス | 説明 |
|-----------|------|------|
| タスクID | `data.taskId` | Bash タスク ID |
| 経過時間 | `data.elapsedTimeSeconds` | 経過時間（秒） |
| 出力サイズ | `data.totalBytes` | 出力バイト数 |
| タイムアウト | `data.timeoutMs` | タイムアウト設定（ミリ秒） |

#### data.type: `agent_progress`

| フィールド | パス | 説明 |
|-----------|------|------|
| エージェントID | `data.agentId` | サブエージェント ID |
| プロンプト | `data.prompt` | エージェントに渡されたプロンプト |

#### data.type: `mcp_progress`

| フィールド | パス | 説明 |
|-----------|------|------|
| サーバー名 | `data.serverName` | MCP サーバー名 |
| ツール名 | `data.toolName` | 呼び出されたツール名 |
| ステータス | `data.status` | 実行状態（`started` 等） |
| 経過時間 | `data.elapsedTimeMs` | 経過時間（ミリ秒） |

---

### 1.7 `pr-link` メッセージ

セッション中に作成されたPR情報。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `prNumber` | number | PR番号 |
| `prUrl` | string | PRのURL |
| `prRepository` | string | リポジトリ名（`owner/repo` 形式） |

---

### 1.8 `last-prompt` メッセージ

セッションの最後のユーザープロンプトを記録。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `lastPrompt` | string | 最後に入力されたプロンプトのテキスト |

---

### 1.9 `agent-name` メッセージ

セッションに割り当てられたエージェント名。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `agentName` | string | エージェント名 |

---

### 1.10 `custom-title` メッセージ

セッションのカスタムタイトル。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `customTitle` | string | カスタムタイトル |

---

### 1.11 `queue-operation` メッセージ

キュー操作の記録。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `operation` | string | `enqueue` または `dequeue` |
| `content` | string | キューに入れられたコンテンツ |

---

### 1.12 `file-history-snapshot` メッセージ

ファイル変更履歴のスナップショット。undo/redo機能に使用される。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `messageId` | string | 関連するメッセージID |
| `isSnapshotUpdate` | boolean | 既存スナップショットの更新か新規作成か |
| `snapshot.trackedFileBackups` | object | 追跡中のファイルバックアップ情報 |
| `snapshot.trackedFileBackups[path].backupFileName` | string | バックアップファイル名 |
| `snapshot.trackedFileBackups[path].version` | number | ファイルバージョン |
| `snapshot.trackedFileBackups[path].backupTime` | string | バックアップ日時 |
| `snapshot.timestamp` | string | スナップショット日時 |

---

## 2. セッションインデックス (`sessions-index.json`)

セッション一覧と要約情報を保持する。`--resume` でセッション選択時などに使用。

```json
{
  "version": 1,
  "entries": [...]
}
```

### エントリフィールド

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `sessionId` | string | セッションの一意ID |
| `fullPath` | string | セッションログファイルの絶対パス |
| `fileMtime` | number | ファイルの最終更新時刻（Unix timestamp ms） |
| `firstPrompt` | string | セッションの最初のユーザー入力 |
| `summary` | string | セッションの要約（自動生成） |
| `messageCount` | number | メッセージ総数 |
| `created` | string (ISO 8601) | セッション作成日時 |
| `modified` | string (ISO 8601) | セッション最終更新日時 |
| `gitBranch` | string | 開始時の git ブランチ |
| `projectPath` | string | プロジェクトのディレクトリパス |
| `isSidechain` | boolean | サイドチェーンかどうか |

---

## 3. ログから取得・分析可能な情報のまとめ

### 3.1 利用統計

| 分析項目 | 取得元 |
|---------|--------|
| セッション数（プロジェクト別） | `.jsonl` ファイル数 |
| メッセージ数（セッション別） | `sessions-index.json` の `messageCount` |
| 使用モデル分布 | `assistant` メッセージの `message.model` |
| トークン使用量（入力/出力） | `assistant` メッセージの `message.usage` |
| キャッシュヒット率 | `cache_read_input_tokens` / 総入力トークン |
| Web検索/フェッチ回数 | `server_tool_use` |
| セッション所要時間 | `system` (subtype: `turn_duration`) の `durationMs` 合計 |
| ターンあたりの平均応答時間 | `turn_duration` の平均値 |

### 3.2 ツール利用分析

| 分析項目 | 取得元 |
|---------|--------|
| ツール別使用頻度 | `assistant` メッセージ内 `tool_use` の `name` |
| ツール別入力パラメータ | `tool_use` の `input` |
| Bash コマンド実行履歴 | `tool_use` (name: `Bash`) の `input.command` |
| ファイル読み取り履歴 | `tool_use` (name: `Read`) の `input.file_path` |
| ファイル編集履歴 | `tool_use` (name: `Edit`) の `input` |
| 検索パターン履歴 | `tool_use` (name: `Grep`) の `input.pattern` |
| ツール実行成否 | `toolUseResult` の `stderr`, `is_error` |

### 3.3 プロジェクト・ブランチ分析

| 分析項目 | 取得元 |
|---------|--------|
| プロジェクト別セッション数 | ディレクトリ名 |
| ブランチ別セッション数 | `gitBranch` フィールド |
| ブランチ間の遷移 | セッション内の `gitBranch` 変化 |
| 作成されたPR一覧 | `pr-link` メッセージ |

### 3.4 ユーザー行動分析

| 分析項目 | 取得元 |
|---------|--------|
| よく聞かれる質問パターン | `user` メッセージの `message.content` |
| セッション開始の最初の質問 | `sessions-index.json` の `firstPrompt` |
| セッション要約 | `sessions-index.json` の `summary` |
| パーミッションモード使用状況 | `user` メッセージの `permissionMode` |
| 起動元分布（CLI/IDE） | `entrypoint` フィールド |
| 作業時間帯分析 | `timestamp` フィールド |

### 3.5 Hook・システム分析

| 分析項目 | 取得元 |
|---------|--------|
| hook実行頻度・種別 | `progress` メッセージの `data.hookEvent` |
| hook実行時間 | `system` (subtype: `stop_hook_summary`) の `hookInfos[].durationMs` |
| hookエラー | `hookErrors` |
| hookによる会話中断 | `preventedContinuation` |

### 3.6 Claude Code バージョン履歴

| 分析項目 | 取得元 |
|---------|--------|
| 使用バージョン履歴 | `version` フィールド |
| バージョンアップの時系列 | `version` × `timestamp` |

### 3.7 ファイル変更追跡

| 分析項目 | 取得元 |
|---------|--------|
| セッション中に変更されたファイル一覧 | `file-history-snapshot` の `trackedFileBackups` |
| ファイルの変更バージョン数 | `trackedFileBackups[path].version` |
| ファイル変更タイミング | `trackedFileBackups[path].backupTime` |

---

## 4. 注意事項

- セッションログには Claude の内部思考（`thinking`）も含まれるが、署名（`signature`）で改ざん検知される
- `sessions-index.json` は全プロジェクトにあるわけではなく、存在しないプロジェクトもある
- `toolUseResult` の `stdout` にはファイル内容やコマンド出力がそのまま含まれるため、機密情報が含まれる可能性がある
- `parentUuid` によるツリー構造で、会話の分岐や並列処理の履歴を復元できる
- ログ全体のサイズは蓄積されるため、長期間使用すると数GB規模になりうる（現在約82MB、358セッション）

---

## 5. JSON Schema

対応する JSON Schema は以下に配置:

- `schemas/session-log-message.schema.json` — セッションログ（.jsonl）の1行のスキーマ
- `schemas/sessions-index.schema.json` — sessions-index.json のスキーマ
