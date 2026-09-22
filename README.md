# agent-otel-stack

OpenTelemetry for **Claude Code** and **GitHub Copilot**, verified against what
they actually ship — not against what their documentation says they ship.

Twelve of those differences are traps: a setup that looks correct, reports
success, and gives you wrong or missing data. What you get here is a
redaction-first collector, a local stack that proves it works, and checks that
re-verify every claim below against the build on your machine.

## Quickstart

```sh
just stack-init   # local dev token in a gitignored .env
just up           # agent + gateway + prometheus + loki + tempo + grafana
just stack-check  # posts one span, proves it reaches Tempo
just settings     # the env block to paste into ~/.claude/settings.json
```

Grafana on `http://127.0.0.1:3000`, with Pipeline Health and Claude Code cost
dashboards provisioned.

`stack-check` proves the pipe, not your data. Paste what `just settings` prints
into `~/.claude/settings.json`, start a new session, and the cost dashboard fills
in as you work — metrics land within `OTEL_METRIC_EXPORT_INTERVAL`, ten seconds.
For Copilot, whose settings are not environment variables at all, the keys are in
[`otel/env/copilot-vscode.env`](otel/env/copilot-vscode.env) ready to paste.

Two checks need no stack and no collector at all — `just smoke` reports what
Claude Code emits on your build (two billed calls), and `just copilot-smoke`
reads Copilot's exporter straight off disk, needing no seat and no sign-in.

That last property cuts both ways: a bundle is readable whether or not you can
use it, so every Copilot check here can pass on an account with no seat. If
Copilot telemetry never arrives, run `just copilot-account` before re-reading
your config — see [docs/07-entitlement.md](docs/07-entitlement.md).

> [!IMPORTANT]
> **The stack is for verifying these configs on your machine, not for
> production.** Grafana runs without auth and the agent→gateway hop is plain
> HTTP. What it does share with a real deployment is the configs — both
> collectors mount [`otel/collector-agent.yaml`](otel/collector-agent.yaml) and
> [`otel/collector-gateway.yaml`](otel/collector-gateway.yaml) directly, so if
> those are wrong it fails to start. Details in
> [docs/06-stack.md](docs/06-stack.md). Still absent: Helm values and TLS.

## Three producers, two of them called Copilot

| | Claude Code | Copilot — VS Code | Copilot — CLI |
|---|---|---|---|
| Metric namespace | `claude_code.*` | `copilot_chat.*` | `github.copilot.*` |
| Cost metric | ✅ | ❌ | ❌ |
| Billing attrs on spans | n/a | ❌ none | ✅ `nano_aiu` |
| Exports to `http://` | ✅ | ✅ | ✅ — but **refuses to attach managed headers**, trap 2 |
| Cache-hit rate from | **metrics** | **traces only** | **traces only** |

VS Code also runs an **agent host process** alongside the chat extension. It has
**no settings of its own**: it binds a loopback OTLP receiver, spawns the CLI as
a child, and relays — see [docs/02-copilot.md](docs/02-copilot.md).

Copilot ships **built into VS Code**, so its settings schema and its exporter
code are readable on disk with no seat. Copilot claims here are pinned to
copilot-chat **0.60.0** / VS Code **1.132.0** and verified **2026-09-21**;
`just copilot-check` re-verifies them on your install.

## The twelve traps

| # | Symptom | Cause | Fix |
|---|---|---|---|
| [1](docs/00-traps.md#1-no-default-protocol) | Nothing arrives, no error | `OTEL_EXPORTER_OTLP_PROTOCOL` has no default and throws | Set it explicitly |
| [2](docs/00-traps.md#2-the-cli-refuses-http--for-enterprise-headers-not-for-export) | Enterprise headers never reach the collector | The CLI refuses to stamp managed headers onto a cleartext endpoint | `https://` + `OTEL_EXPORTER_OTLP_CERTIFICATE` |
| [3](docs/00-traps.md#3-delta-versus-cumulative) | Dead for 60 s, then wrong counters | `delta` default, 60 s interval | `cumulative`, 10 s |
| [4](docs/00-traps.md#4-two-identifiers-you-cannot-turn-off) | Team emails in your TSDB, permanently | `user.email` has no kill switch | The collector |
| [5](docs/00-traps.md#5-response-logging-turns-itself-on) | Model output exported after an upgrade | `OTEL_LOG_ASSISTANT_RESPONSES` inherits the prompt flag | Set it to `0` |
| [6](docs/00-traps.md#6-nano_aiu-is-duplicated-onto-children) | Copilot cost roughly doubled | `nano_aiu` is stamped on parent *and* children | Root span only |
| [7](docs/00-traps.md#7-copilot-has-no-cost-metric) | No Copilot cost at all | Copilot emits none | Usage Metrics API |
| [8](docs/00-traps.md#8-the-file-exporter-writes-empty-spans) | A big file of valid JSON, zero traces in it | `JSON.stringify` hits a circular span reference; the `catch` writes `{}` | Never `outfile` for traces — `enabled` **+** `dbSpanExporter` |
| [9](docs/00-traps.md#9-the-endpoint-variable-is-an-on-switch) | Copilot exporting when you only configured Claude Code | `OTEL_EXPORTER_OTLP_ENDPOINT` alone enables Copilot's OTel | Know it is a switch, not just a destination |
| [10](docs/00-traps.md#10-a-typo-in-the-endpoint-sends-data-to-localhost) | A remote endpoint configured, nothing ever arrives | `new URL()` throws, the catch falls back to `localhost:4318` | Check `enabledVia` in the Copilot Chat log |
| [11](docs/00-traps.md#11-the-protocol-setting-and-the-variable-disagree) | `protocol: "grpc"` set, `http/json` on the wire | The setting feeds the protocol only; the env var also feeds transport | Use `exporterType: otlp-grpc` |
| [12](docs/00-traps.md#12-prometheus-renames-every-metric-you-send-it) | Every dashboard panel empty, no error | Prometheus's OTLP receiver rewrites names and folds the unit in | Query the stored name, not the documented one |

## What's in the repo

| Path | What |
|---|---|
| [`docs/00-traps.md`](docs/00-traps.md) | The twelve traps, in full |
| [`docs/01-claude-code.md`](docs/01-claude-code.md) | Enablement, metrics, events, beta traces |
| [`docs/02-copilot.md`](docs/02-copilot.md) | Five surfaces, two engines, span hierarchy |
| [`docs/03-privacy.md`](docs/03-privacy.md) | What leaves the machine, and what cannot be turned off |
| [`docs/05-normalization.md`](docs/05-normalization.md) | Joining the three shapes — and what cannot be joined |
| [`docs/06-stack.md`](docs/06-stack.md) | The local stack: topology, and what to check when it will not start |
| [`docs/07-entitlement.md`](docs/07-entitlement.md) | Seats: why a perfect config still produces nothing |
| [`otel/collector-agent.yaml`](otel/collector-agent.yaml) | Laptop-resident: redaction **and** a queue that survives sleep |
| [`otel/collector-gateway.yaml`](otel/collector-gateway.yaml) | Beside the backends: fan-out to Prometheus, Loki, Tempo |
| [`otel/env/`](otel/env/) | Per-surface enablement — the lines you actually set |
| `tools/smoke.sh` | `just smoke` — verifies Claude Code's surface on your build |
| `tools/copilot_smoke.py` | `just copilot-smoke` — verifies Copilot's surface **with no seat** |
| `tools/copilot_check.py` | Fails if a documented Copilot setting's **name, type or default** has drifted |
| `tools/copilot_traces.py` | `just copilot-traces` — what is in the local SQLite span store |
| `tools/otel_check.py` | Validates the collector config **without the collector binary** |
| `tools/dash-check.sh` | Rejects dashboards that won't bind to a provisioned datasource |
| `tools/paths.py` | Fails if a comment points at a repo file that does not exist |
| `tools/trap_check.py` | Fails on a dead trap anchor or a stale trap count — nothing else sees these |
| `tools/leaks.sh` · `links.sh` · `refs.sh` | Credential-shaped strings, relative links, reference-style links |
| `tools/lint.sh` · `fmt.sh` | shellcheck + ruff, shfmt + ruff format — both languages, one command each |
| `tools/test_tools.py` | `just test` — the gates' own self-tests, including the drills that used to die with the session |
| `tools/lib/common.sh` · `lib/report.py` | Shared helpers; the two halves print identical glyphs |
| `.github/workflows/check.yml` | `just check` + `just test` on every push and PR |
| `justfile` · `lefthook.yml` | `just check` runs every gate; lefthook runs it pre-commit |

Every tool is written in exactly one language, chosen by what it does: the gates
that parse structure are Python, the gates that orchestrate other binaries are
shell. Nothing embeds one language inside the other, because a heredoc body is
invisible to both linters.

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
