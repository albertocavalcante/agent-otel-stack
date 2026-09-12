# agent-otel-stack

OpenTelemetry for **Claude Code** and **GitHub Copilot**: enablement per surface, a
redaction-first collector config, and checks that run without a collector.

> [!CAUTION]
> **Seven ways a working-looking setup gives you wrong or missing data. None of
> them error.**

## Verify your build

```sh
just smoke     # what Claude Code actually emits here — no collector, two prompts
```

It runs `claude -p` twice, so it makes two billed calls and writes a session
transcript to `~/.claude/projects/` like any other run. Only the OTel output
goes to a temp dir, which is deleted.

Claims below are pinned to Claude Code **v2.1.220** and verified **2026-09-12**;
`just smoke` re-verifies them on whatever you are running.

## The seven traps

| # | Symptom | Cause | Fix |
|---|---|---|---|
| [1](#1-no-default-protocol) | Nothing arrives, no error | `OTEL_EXPORTER_OTLP_PROTOCOL` has no default and throws | Set it explicitly |
| [2](#2-the-copilot-cli-refuses-http) | VS Code data arrives, CLI data never does | CLI silently drops `http://` endpoints | TLS, or the file exporter |
| [3](#3-delta-versus-cumulative) | Dead for 60 s, then wrong counters | `delta` default, 60 s interval | `cumulative`, 10 s |
| [4](#4-two-identifiers-you-cannot-turn-off) | Team emails in your TSDB, permanently | `user.email` has no kill switch | The collector |
| [5](#5-response-logging-turns-itself-on) | Model output exported after an upgrade | `OTEL_LOG_ASSISTANT_RESPONSES` inherits the prompt flag | Set it to `0` |
| [6](#6-nano_aiu-is-duplicated-onto-children) | Copilot cost roughly doubled | `nano_aiu` is stamped on parent *and* children | Root span only |
| [7](#7-copilot-has-no-cost-metric) | No Copilot cost at all | Copilot emits none | Usage Metrics API |

### 1. No default protocol

Claude Code throws `Unknown protocol set in … env var: undefined` and exports
nothing. [`monitoring-usage`][cc-mon] is explicit: *"Claude Code has no default
protocol, so set this or the signal-specific protocol variable for each `otlp`
exporter you enable."*

### 2. The Copilot CLI refuses `http://`

Export is dropped *"rather than sent in cleartext; startup is not aborted"* — no
warning, no non-zero exit ([copilot-cli#4567][cli4567], open as of 2026-09-12). **The VS Code
extension exports to the same endpoint fine**, so one collector on
`localhost:4318` collects half your data silently.
Workarounds: [`otel/env/copilot-cli.env`](otel/env/copilot-cli.env).

### 3. delta versus cumulative

Prometheus needs `cumulative`. At the 60 s default interval you get a minute of
silence, then counters that are wrong rather than absent.

### 4. Two identifiers you cannot turn off

No environment variable disables `user.email` or `organization.id`. Anthropic:
*"Always included when available."* Copilot's `github.copilot.git.repository`
(your remote URL), `.branch`, `.commit_sha` and org name are always on too.

**This is the argument for a collector.** Prometheus, Loki and Tempo all accept
OTLP directly — going direct means storing your team's email addresses in a
time-series database, permanently, by default.

### 5. Response logging turns itself on

`OTEL_LOG_ASSISTANT_RESPONSES` *follows* `OTEL_LOG_USER_PROMPTS` when unset, so
prompt logging began exporting model output on upgrade to 2.1.193 with no config
change. [`otel/env/claude-code.env`](otel/env/claude-code.env) sets it explicitly.

### 6. `nano_aiu` is duplicated onto children

`github.copilot.nano_aiu` is stamped on the root `invoke_agent` span **and on
every child `chat` span**, so summing across spans double-counts. Read the root
only.

**The unit is billionths of an AI unit — divide by 1e9.** A dashboard that
plots it raw is wrong by a factor of a billion. And `github.copilot.cost` is a
per-request **model multiplier, not a currency value**.

> [!NOTE]
> We have not located a GitHub-authored page stating the duplication rule in
> those words. The behaviour is corroborated by
> [copilot-cli#4224][cli4224] and by third-party integrations; treat the exact
> wording as **unverified** until GitHub documents it.

### 7. Copilot has no cost metric

[copilot-cli#3778][cli3778] — a user-filed feature request, open as of 2026-09-12 — asks for parity with
`claude_code.cost.usage`. Until then, Copilot cost comes from the Usage Metrics
API, not from OTel.

## What each harness emits

| | Claude Code | GitHub Copilot |
|---|---|---|
| Metrics | 8, including cost and token type | `gen_ai.*` + vendor; **no cost** |
| Cache tokens | `claude_code.token.usage{type=cacheRead}` | **traces only** ([vscode#317837][vs317837], open as of 2026-09-12) |
| Traces | beta, env-gated, works today | GA, the primary signal |
| Metric namespace | `claude_code.*` | `copilot_chat.*` (VS Code) · `github.copilot.*` (CLI) |

Cache-hit rate is span-only on both surfaces. Build trace-first. And one
dashboard cannot serve both harnesses — the namespaces and the cost story differ.

## If you are pinned below 2.1.268

Current release is **2.1.269**. All three of these are already fixed upstream —
they apply only to older installs, and this repo's claims were verified on
2.1.220. Sources: [`monitoring-usage`][cc-mon] and the [CHANGELOG][cc-log].

| Behaviour on an older build | Fixed in |
|---|---|
| MCP attribution inflated — `mcp_server.name` set on every request after an MCP call | 2.1.222 |
| `cost.usage` is **list price**; contracted rates need `modelPricing` | 2.1.243 |
| Bounded `*_safe` span attributes absent — hand-allowlist span-metric dimensions | 2.1.268 |

Anthropic warns that dashboards *"show a step down after you upgrade"* past the
first. `just smoke` prints your version.

## What's in the repo

| Path | What |
|---|---|
| [`otel/collector.yaml`](otel/collector.yaml) | Redaction-first collector, `otelcol-contrib` 0.160.0 |
| [`otel/env/`](otel/env/) | Per-surface enablement — the lines you actually set |
| `tools/smoke.sh` | `just smoke` — verifies the surface on your build |
| `tools/otel-check.sh` | Validates the collector config **without the collector binary** |
| `tools/dash-check.sh` | Rejects dashboards that won't bind to a provisioned datasource |
| `tools/lib/common.sh` | Shared helpers and the leak pattern |
| `justfile` · `lefthook.yml` | `just check` runs every gate; lefthook runs it pre-commit |

## Status

v1 ships configs and checks, no running stack. Compose, dashboards and a Helm
values file come next.

`grafana/lgtm-distributed` is hard-deprecated — do not reach for it.

## Prior art

- [`ColeMurray/claude-code-otel`](https://github.com/ColeMurray/claude-code-otel)
  (MIT) — the reference implementation, last pushed 2025-06-17, predating the
  trace tier
- [Grafana Cloud's Claude Code integration](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-infrastructure/integrations/integration-reference/integration-claude-code/) — official, first-party
- [Microsoft Learn — monitoring AI coding agents](https://learn.microsoft.com/en-us/azure/managed-grafana/grafana-opentelemetry-app-insights) — the densest cross-agent doc
- [AWS Coding Agent Insights](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/coding-agents-claude-code.html)

Dashboards published on grafana.com carry **no licence field**. This repo does not
vendor their JSON.

Cost analysis of the same two harnesses:
[`harness-economics`](https://github.com/albertocavalcante/harness-economics).

## Licence

Apache-2.0.

[cc-mon]: https://code.claude.com/docs/en/monitoring-usage
[cli4567]: https://github.com/github/copilot-cli/issues/4567
[cli3778]: https://github.com/github/copilot-cli/issues/3778
[vs317837]: https://github.com/microsoft/vscode/issues/317837
[cli4224]: https://github.com/github/copilot-cli/issues/4224
[cc-log]: https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
