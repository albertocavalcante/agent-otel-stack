# Three products, not two

"Claude Code versus Copilot" is the wrong frame. There are **three distinct
telemetry producers**, and two of them are both called Copilot.

| | Claude Code | Copilot — VS Code | Copilot — CLI |
|---|---|---|---|
| **Enabled by** | `CLAUDE_CODE_ENABLE_TELEMETRY=1` | `github.copilot.chat.otel.enabled` | `COPILOT_OTEL_ENABLED` |
| **Configured in** | env / `settings.json` `env` block | VS Code settings | env only |
| **Metric namespace** | `claude_code.*` | `copilot_chat.*` | `github.copilot.*` |
| **Signals** | metrics, events, beta traces | traces + metrics | traces + metrics |
| **Cost metric** | ✅ `claude_code.cost.usage` | ❌ | ❌ |
| **Billing attrs on spans** | n/a | ❌ **none at all** | ✅ `nano_aiu`, `cost` |
| **Exports to `http://`** | ✅ | ✅ | ❌ **silently refuses** |
| **Transport** | grpc, http/json, http/protobuf | otlp-http, otlp-grpc, console, file | otlp-http, file — **no grpc** |
| **Default protocol** | **none — throws** | `otlp-http` | `otlp-http` |

Everything below is a consequence of that table.

## The four mistakes this table prevents

### 1. Treating "Copilot" as one thing

The VS Code extension and the CLI are separate implementations on separate
release trains. A benchmark, a bug report, or a dashboard for one **does not
transfer to the other**. They disagree on transport, on metric names, and on
whether spans carry billing data at all.

### 2. Assuming one collector endpoint serves both

`http://localhost:4318` works for VS Code and is **silently dropped** by the CLI
([copilot-cli#4567][cli4567], open). You get extension data, no CLI data, and no
error. See [02-copilot.md](02-copilot.md).

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
configurable.

> [!WARNING]
> **Unconfirmed:** a separate `chat.agentHost.otel.*` settings namespace is
> reported in a GitHub issue, but the VS Code settings documentation lists only
> the eight `github.copilot.chat.otel.*` keys and no agent-host equivalent. We
> have not verified it and do not assert it.
>
> What follows regardless: the agent host runs the **CLI runtime**, so the CLI's
> refusal to export over `http://` can bite you *inside VS Code*. If extension
> spans arrive and agent turns do not, that is the first thing to check.

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
> from both ([copilot-cli#4224][cli4224], open), so `invoke_agent` alone
> undercounts by roughly 10–15%.

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
