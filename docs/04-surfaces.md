# Three products, not two

"Claude Code versus Copilot" is the wrong frame. There are **three distinct
telemetry producers**, and two of them are both called Copilot.

| | Claude Code | Copilot — VS Code | Copilot — CLI |
|---|---|---|---|
| **Enabled by** | `CLAUDE_CODE_ENABLE_TELEMETRY=1` | `otel.enabled` — **or `OTEL_EXPORTER_OTLP_ENDPOINT` alone** | `COPILOT_OTEL_ENABLED`, or the endpoint alone |
| **Configured in** | env / `settings.json` `env` block | VS Code settings | env only |
| **Metric namespace** | `claude_code.*` | `copilot_chat.*` | `github.copilot.*` |
| **Signals** | metrics, events, beta traces | traces + metrics | traces + metrics |
| **Cost metric** | ✅ `claude_code.cost.usage` | ❌ | ❌ |
| **Billing attrs on spans** | n/a | ❌ **none at all** | ✅ `nano_aiu`, `cost` |
| **Exports to `http://`** | ✅ | ✅ | ✅ — but **will not attach managed headers** to it |
| **Exporter selection** | `OTEL_{METRICS,LOGS,TRACES}_EXPORTER` | `exporterType`: otlp-http, otlp-grpc, console, file | `COPILOT_OTEL_EXPORTER_TYPE`: otlp-http, file — **no grpc** |
| **Default exporter** | unset — off | `otlp-http` | `otlp-http` |
| **Wire protocol** | `OTEL_EXPORTER_OTLP_PROTOCOL` — **none, throws** | `http/json` by default; the `protocol` setting cannot select grpc | `http/json`; `http/protobuf` needs v1.0.61+ |
| **Recoverable after the fact** | ❌ nothing local | ✅ `agent-traces.db` — spans only, **lossy**, `just copilot-traces` | ❌ file exporter output only, format unverified |

> [!NOTE]
> The middle two rows are not the same question. `otlp-http` and `file` are
> **exporter types** — `console` and `file` are sinks, not transports — while
> `http/json` and `grpc` are wire protocols. Copilot exposes both as separate
> settings and they interact badly: see README trap 11.

Everything below is a consequence of that table.

## The four mistakes this table prevents

### 1. Treating "Copilot" as one thing

The VS Code extension and the CLI are separate implementations on separate
release trains. A benchmark, a bug report, or a dashboard for one **does not
transfer to the other**. They disagree on transport, on metric names, and on
whether spans carry billing data at all.

### 2. Assuming one collector endpoint serves both

`http://localhost:4318` works for both. What the CLI will not do is attach
**enterprise managed headers** to a cleartext or user-controlled endpoint
([copilot-cli#4567][cli4567], open). For an individual developer with no managed
telemetry that changes nothing; for an enterprise it means the credentials are
silently withheld. See [02-copilot.md](02-copilot.md).

### 3. Writing one dashboard

`copilot_chat.tool.call.count` and `github.copilot.tool.call.count` are different
series. A panel written against one is empty against the other. Claude Code
shares nothing with either.

### 4. Looking for Copilot cost in OTel

Only Claude Code emits a cost metric. On the Copilot CLI you can *derive* spend
from `github.copilot.nano_aiu` — root span only, divided by 1e9 — and on the VS
Code extension you cannot derive it at all, because those spans carry no billing
attributes. Copilot cost comes from the Usage Metrics API.

## VS Code runs two things

The Copilot Chat extension is not the only telemetry producer inside VS Code.
There is also an **agent host process**, and the enterprise documentation is
explicit that managed telemetry *"applies to both the Copilot Chat extension and
the agent host process"* — which is only worth saying if they are separately
configurable. They are.

> [!CAUTION]
> **A previous revision of this file claimed a `chat.agentHost.otel.*` settings
> namespace is "confirmed present". That was wrong and is retracted.** The
> string occurs **zero** times in `agentHostMain.js`, in the extension bundle,
> and in `package.json`. The claim came from a grep for `agentHost.otel` that
> matched log tags — `[agentHost-otel] receiver: …` — and a DI service brand,
> `agentHostOTelService`. Neither is a setting.
>
> There is **no separate settings namespace for the agent host.** The eleven
> `github.copilot.chat.otel.*` keys are the whole user-facing surface.

What the agent host *does* have, read from the same build, is its own
**in-process OTLP receiver on loopback**:

```js
i.listen(0, "127.0.0.1", …)
n.info(`[agentHost-otel] receiver listening on http://127.0.0.1:${port}`)
```

It binds an ephemeral port, spawns the Copilot CLI as a stdio child pointed at
it, and forwards what arrives onward. So the agent host is a *relay*, not a
second independently-configured exporter — which is why it has no settings of
its own, and why its telemetry follows the extension's configuration.

That it spawns the CLI is observed, not inferred — `agentHostMain.js` contains
`"[Copilot] Starting CopilotClient..."` and constructs the child over stdio. So
the CLI's behaviour does reach you inside VS Code; it is the `http://` half of
the old inference that was wrong, not this half.

## Where each one's cache data lives

The question this repo exists for, and the answer differs by surface:

| Surface | Cache-hit rate obtainable from |
|---|---|
| Claude Code | **metrics** — `claude_code.token.usage{type=cacheRead}` |
| Copilot, either surface | **traces only** — `gen_ai.usage.cache_read.input_tokens` |

Copilot's metrics omit cache fields entirely
([vscode#317837][vs317837], open). So a metrics-only pipeline gives you a cache
hit rate for Claude Code and silently gives you nothing for Copilot — which reads
as "Copilot has no cache", not as "this pipeline cannot see it."

**Build trace-first if you need both.**

## Aggregation rules differ too

Claude Code metrics are counters; sum them normally.

Copilot spans are **not** safe to sum. `invoke_agent` is the root and its token
counts already include every child `chat` span — *"total input tokens (all
turns)"*. And `nano_aiu` is duplicated onto the children outright.

> [!IMPORTANT]
> On Copilot, aggregate at **exactly one level**: `chat` for per-model, or
> `invoke_agent` for per-turn. Never both. And note subagent spend is missing
> from both ([copilot-cli#4224][cli4224], **closed 2026-09-20, fixed in CLI
> v1.0.86**), so on older builds `invoke_agent` alone undercounts by roughly
> 10–15%.

## Which is easier to instrument

Honestly: **Claude Code**, for three reasons.

1. One producer, one namespace, one set of env vars.
2. A cost metric, so spend needs no derivation.
3. `just smoke` can verify the whole surface in thirty seconds with no collector.

Copilot's advantages are real but narrower: GA rather than beta traces,
enterprise-managed export, and `edit.survival.*` metrics that measure whether
suggested edits survived — something Claude Code does not emit at all.

[cli4567]: https://github.com/github/copilot-cli/issues/4567
[cli4224]: https://github.com/github/copilot-cli/issues/4224
[vs317837]: https://github.com/microsoft/vscode/issues/317837
