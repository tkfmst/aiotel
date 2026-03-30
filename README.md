# aiotel

`aiotel` は、標準入力から Claude Code の session JSONL を読み込み、`skill` の使用イベントを抽出して OpenTelemetry メトリクスとして送信する小さな Go CLI です。

## 実行方法

まずローカルの観測基盤を起動します。

```bash
docker compose up -d
```

次に、Claude の session log を標準入力から CLI に渡します。

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
go run ./cmd/aiotel-claude-skill-metrics < ~/.claude/projects/<project>/<session>.jsonl
```

送信する `user` ラベルを明示的に上書きしたい場合は `AIOTEL_USER` を指定します。

```bash
AIOTEL_USER=john.doe \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
go run ./cmd/aiotel-claude-skill-metrics < ~/.claude/projects/<project>/<session>.jsonl
```

主な環境変数は次のとおりです。

- `AIOTEL_USER`: 実行ユーザーのラベルを上書きします。未指定時は OS ユーザー名にフォールバックします。
- `OTEL_EXPORTER_OTLP_ENDPOINT`: Collector の OTLP HTTP endpoint を指定します。
- `OTEL_SERVICE_NAME`: OTel の service name を指定します。既定値は `aiotel-claude-skill-metrics` です。
- `AIOTEL_METRIC_EXPORT_INTERVAL`: メトリクスの flush 間隔です。既定値は `5s` です。

Prometheus は `http://localhost:9090`、Grafana は `http://localhost:3000` で利用できます。Grafana の初期ログインは `admin` / `admin` です。

Prometheus での確認例です。

```promql
sum by (skill_name, branch) (increase(aiotel_skill_usage_total[1h]))
```

送信されるメトリクスは次です。

- `aiotel_skill_usage_total{user,repository,branch,skill_name,success}`

Claude JSONL に含まれるイベント時刻は内部では parse しますが、Prometheus のサンプル時刻として使われるのは観測時刻です。時系列で見たい場合はクエリ側で range を使って集計してください。

## ドキュメント

- [Codex sessions log](docs/codex/codex-sessions-log.md)
- [Codex sessions record schema](docs/codex/codex-session-record.schema.json)
- [Claude Code session log spec](docs/claude/claude-code-session-log-spec.md)
