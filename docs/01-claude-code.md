# Claude Code

Verified **2026-09-12** against the v2.1.220 binary and
[`monitoring-usage`][mon]. Current release is **2.1.269** — where a claim is
version-bound it says so.

Config lives in [`../otel/env/claude-code.env`](../otel/env/claude-code.env).
Run [`just smoke`](../justfile) to confirm any of this on your own build.

## Enabling it

`CLAUDE_CODE_ENABLE_TELEMETRY=1` is the only gate on third-party export. It is
Claude-Code-specific, not an OTel SDK variable.

| Variable | Accepted | Default |
|---|---|---|
| `OTEL_METRICS_EXPORTER` | `console`, `otlp`, `prometheus`, `none` | unset — off |
| `OTEL_LOGS_EXPORTER` | `console`, `otlp`, `none` | unset — off |
| `OTEL_TRACES_EXPORTER` | `console`, `otlp`, `none` | unset — off |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc`, `http/json`, `http/protobuf` | **none — required** |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | base URL, no signal path | — |
| `OTEL_METRIC_EXPORT_INTERVAL` | ms | `60000` |
| `OTEL_LOGS_EXPORT_INTERVAL` | ms | `5000` |
| `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE` | `delta`, `cumulative` | `delta` |

> [!IMPORTANT]
> **There is no default protocol.** [`monitoring-usage`][mon]: *"Claude Code has
> no default protocol, so set this or the signal-specific protocol variable for
> each `otlp` exporter you enable."* Omit it and export fails outright.

Per-signal overrides exist for protocol, endpoint and headers
(`OTEL_EXPORTER_OTLP_{METRICS,LOGS,TRACES}_*`). Endpoint and protocol override
the generic value; **headers merge** with it.

`OTEL_*` variables are **not inherited by subprocesses** — Bash tool invocations,
hooks, MCP servers, LSPs. An instrumented app you launch from Claude Code will
not pick up your collector endpoint.

## The eight metrics

That is the complete list. Anything else you have read about is a span (below) or
does not exist.

| Metric | Unit | Notable attributes |
|---|---|---|
| `claude_code.session.count` | — | `start_type` = `fresh`/`resume`/`continue` |
| `claude_code.lines_of_code.count` | — | `type` = `added`/`removed`, `model` |
| `claude_code.pull_request.count` | — | — |
| `claude_code.commit.count` | — | — |
| `claude_code.cost.usage` | USD | `model`, `query_source`, `effort`, `agent.name`, `mcp_server.name` |
| `claude_code.token.usage` | tokens | `type` = `input`/`output`/`cacheRead`/`cacheCreation` |
| `claude_code.code_edit_tool.decision` | — | `tool_name`, `decision`, `source`, `language` |
| `claude_code.active_time.total` | s | `type` = `user`/`cli` |

Attribution attributes are bounded by design: built-in and official-marketplace
names appear verbatim, user-defined ones collapse to `custom`, third-party
plugins to `third-party`. That is what keeps `agent.name` and `mcp_server.name`
from being unbounded labels.

> [!NOTE]
> Under a `prometheus`-only exporter the `USD`/`tokens`/`s` units are omitted so
> the scrape stays valid Prometheus text. Metric names are unchanged. Combined
> exporters (`otlp,prometheus`) keep units.

## Events

Nine are documented. `claude_code.api_request` is **the only one carrying both
token counts and cost**.

| Event | Tokens | Cost | Content, and its gate |
|---|:--:|:--:|---|
| `user_prompt` | | | `prompt` — `OTEL_LOG_USER_PROMPTS` |
| `assistant_response` | | | `response` — `OTEL_LOG_ASSISTANT_RESPONSES` |
| `tool_result` | | | `tool_input` — `OTEL_LOG_TOOL_DETAILS` |
| `tool_decision` | | | `tool_input` — `OTEL_LOG_TOOL_DETAILS` |
| **`api_request`** | ✅ | ✅ | — |
| `api_error` | | | error message |
| `api_refusal` | | | `category` — `OTEL_LOG_TOOL_DETAILS` |
| `api_request_body` | | | **entire conversation** — `OTEL_LOG_RAW_API_BODIES` |
| `api_response_body` | | | **full response** — same |

The event name lands in the log record **body** as `claude_code.<name>` and in the
`event.name` attribute **without** the prefix. A Loki pipeline filtering on one
must not use the other's form.

Correlate with `prompt.id` (one per user prompt), `message.uuid`, `request_id`,
and `tool_use_id` — which joins `tool_decision` → `tool_result` → the
`claude_code.tool` span.

> [!WARNING]
> The binary contains **16 further event names** that are undocumented, including
> one that emits full tool *definitions*. Undocumented events are not a stable
> contract; do not build panels on them.

## Traces

Beta, off by default, and **working on 2.1.220** — gated by an environment
variable alone, with no org allowlist and no server-side flag.

```sh
CLAUDE_CODE_ENABLE_TELEMETRY=1
CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
```

```
claude_code.interaction          ← root, one per user prompt
├── claude_code.llm_request
├── claude_code.hook
└── claude_code.tool
    ├── claude_code.tool.blocked_on_user
    └── claude_code.tool.execution
```

`just smoke` reproduces this. Bash subprocesses inherit `TRACEPARENT` from the
active tool-execution span; `claude -p` and the Agent SDK read an inbound
`TRACEPARENT`, while interactive sessions ignore it.

> [!CAUTION]
> **Four span names in the bundle never emit.** `claude_code.subagent.spawn`,
> `.bash.subprocess`, `.compaction` and `.mcp.rpc` are all constructed through a
> helper gated on a function that is a constant `false` in this build. They are
> undocumented and must not appear in a dashboard. `just smoke` asserts their
> absence and warns — not fails — if a future build enables them.

## Identity attributes

These are **datapoint and log-record attributes, not resource attributes** — the
distinction drives the whole cardinality story.

| Attribute | Switch | Default |
|---|---|---|
| `user.id` | **none** | always |
| `session.id` | `OTEL_METRICS_INCLUDE_SESSION_ID` | `true` |
| `user.account_uuid` | `OTEL_METRICS_INCLUDE_ACCOUNT_UUID` | `true` |
| **`user.email`** | **none** | always when authenticated |
| **`organization.id`** | **none** | always when authenticated |
| `app.version` | `OTEL_METRICS_INCLUDE_VERSION` | `false` |

`service.name`, `service.version`, `os.type`, `os.version` and `host.arch` are the
resource block. **`host.name` and `host.id` are deliberately filtered out** — a
good privacy default worth knowing about.

See [03-privacy.md](03-privacy.md).

## If you are pinned below 2.1.268

| Behaviour | Fixed in |
|---|---|
| `mcp_server.name` set on every request after an MCP call, not only those consuming a result | 2.1.222 |
| `cost.usage` uses list price; contracted rates need the `modelPricing` managed setting | 2.1.243 |
| Bounded `tool_name_safe` / `query_source_safe` span attributes absent | 2.1.268 |

The third matters if you derive span metrics: on 2.1.220 the raw `tool_name` and
`query_source` include MCP tool names and arbitrary subagent names, both
unbounded. Allowlist your dimensions by hand.

[mon]: https://code.claude.com/docs/en/monitoring-usage
