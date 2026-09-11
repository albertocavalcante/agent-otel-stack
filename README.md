# agent-otel-stack

OpenTelemetry for **Claude Code** and **GitHub Copilot** — enablement, a
redaction-first collector config, and a smoke test that verifies the documented
behaviour on *your* build without a collector, a container, or a byte of disk.

**Verified 2026-09-11** against the Claude Code v2.1.220 binary, both vendors'
docs, and the VS Code / Copilot CLI issue trackers. Every claim carries a source.

> [!CAUTION]
> **A naive setup silently produces wrong or absent data in five ways.** None of
> them error. Each is a section below, and each is why this repo exists rather
> than a compose file.

## Start here

```sh
just smoke          # verify Claude Code's telemetry on this machine — no collector needed
just check          # lint, links, leaks, collector config, dashboard bindings
```

`just smoke` is the point of v1. It costs one trivial prompt, writes only to a
temp dir it then deletes, and tells you what your build actually emits.

## The five traps

### 1. `OTEL_EXPORTER_OTLP_PROTOCOL` has no default, and omitting it throws

Claude Code raises `Unknown protocol set in … env var: undefined` and exports
nothing. **Anthropic's own [env-vars page][cc-env] still says `grpc (default)`** —
that page is stale; [`monitoring-usage`][cc-mon] and the shipped binary agree
there is no default. This is the most likely cause of "I enabled telemetry and
nothing arrived."

### 2. The Copilot CLI silently refuses `http://` endpoints

Including `http://localhost:4318`. Export is dropped *"rather than sent in
cleartext; startup is not aborted"* — no warning, no non-zero exit
([copilot-cli#4567][cli4567], open).

**The VS Code extension exports to that same endpoint fine.** So one collector on
`localhost:4318` receives VS Code data and *nothing* from the CLI, and you
conclude the CLI has no telemetry. Use TLS or the file exporter; see
[`otel/env/copilot-cli.env`](otel/env/copilot-cli.env).

### 3. Metrics default to `delta`; Prometheus needs `cumulative`

Combined with a **60 s** default export interval, a correct setup looks dead for
a minute and then produces counters that are wrong rather than missing — the
harder failure to notice.

### 4. `user.email` and `organization.id` cannot be turned off

No environment variable disables either. Anthropic's docs: *"Always included when
available."* **The collector is the only control point**, which is the entire
argument for running one — Prometheus, Loki and Tempo all accept OTLP directly,
and going direct means storing your team's email addresses in a time-series
database permanently, by default.

On the Copilot side, `github.copilot.git.repository` (your remote URL), `.branch`,
`.commit_sha` and the org name are always on too, with no setting of their own.

### 5. `OTEL_LOG_ASSISTANT_RESPONSES` silently inherits `OTEL_LOG_USER_PROMPTS`

When unset it *follows* the prompt-logging flag. Anyone who had prompt logging on
**began exporting model output on upgrade to 2.1.193 with no config change.**
Always set it explicitly — [`otel/env/claude-code.env`](otel/env/claude-code.env)
does.

## Two more, for anyone computing cost

**`github.copilot.nano_aiu` is duplicated onto child spans.** GitHub's own
reference: read it *"from the root `invoke_agent` span only … summing it across
every span double-counts."* And `github.copilot.cost` is a **per-request model
multiplier, not a currency value**.

**Copilot emits no cost metric at all** ([copilot-cli#3778][cli3778], open), while
Claude Code emits `claude_code.cost.usage`. Copilot cost must come from the Usage
Metrics API instead. **This is why one dashboard cannot serve both harnesses.**

## The two harnesses do not emit the same shape

| | Claude Code | GitHub Copilot |
|---|---|---|
| Metrics | 8, including cost and token type | `gen_ai.*` + vendor; **no cost** |
| Cache tokens | on `claude_code.token.usage{type=cacheRead}` | **traces only** ([vscode#317837][vs317837], open) |
| Traces | beta, env-gated, works today | GA, the primary signal |
| Metric namespace | `claude_code.*` | `copilot_chat.*` (VS Code) · `github.copilot.*` (CLI) |

Copilot's *metrics* omit cache fields entirely, so **cache-hit rate is only
obtainable by parsing spans** — on either surface. Build trace-first.

## Version caveats on Claude Code 2.1.220

| Behaviour | Fixed in |
|---|---|
| MCP attribution inflated — `mcp_server.name` set on every request after an MCP call | 2.1.222 |
| `cost.usage` is **list price**; contracted rates need `modelPricing` | 2.1.243 |
| Bounded `*_safe` span attributes absent — hand-allowlist span-metric dimensions | 2.1.268 |

Anthropic's docs warn that dashboards "show a step down after you upgrade" past
the first one. `just smoke` prints your version alongside the results for exactly
this reason.

## Layout

| Path | What |
|---|---|
| [`otel/collector.yaml`](otel/collector.yaml) | Redaction-first collector, `otelcol-contrib` 0.160.0 |
| [`otel/env/`](otel/env/) | Per-surface enablement, with the traps inline |
| `tools/otel-check.sh` | Validates the collector config **without the collector binary** |
| `tools/dash-check.sh` | Rejects dashboards that won't bind to a provisioned datasource |
| `tools/smoke.sh` | The verification above |

## Status

v1 ships **no running stack** — deliberately. The configs are complete and
validated by `just check`; a compose stack, dashboards and a Helm values file
come next.

The reason is worth stating plainly: the research is the scarce part. Every trap
above is reproducible from this repo today with no image pulled, and
`grafana/lgtm-distributed` — the obvious Helm answer — is hard-deprecated, so
shipping one would have been worse than shipping none.

## Prior art

- [`ColeMurray/claude-code-otel`](https://github.com/ColeMurray/claude-code-otel)
  (MIT, 495★) — the reference implementation, last pushed 2025-06-17, predating
  the trace tier
- [Grafana Cloud's Claude Code integration](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-infrastructure/integrations/integration-reference/integration-claude-code/) — official, first-party
- [Microsoft Learn — monitoring AI coding agents](https://learn.microsoft.com/en-us/azure/managed-grafana/grafana-opentelemetry-app-insights) — the densest cross-agent doc
- [AWS Coding Agent Insights](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/coding-agents-claude-code.html)

> [!NOTE]
> Dashboards published on grafana.com carry **no licence field**. This repo does
> not vendor any of their JSON; anything here is written from scratch.

Cost analysis of these same two harnesses:
[`harness-economics`](https://github.com/albertocavalcante/harness-economics).

Apache-2.0.

[cc-mon]: https://code.claude.com/docs/en/monitoring-usage
[cc-env]: https://code.claude.com/docs/en/env-vars
[cli4567]: https://github.com/github/copilot-cli/issues/4567
[cli3778]: https://github.com/github/copilot-cli/issues/3778
[vs317837]: https://github.com/microsoft/vscode/issues/317837
