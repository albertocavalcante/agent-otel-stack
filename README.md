# agent-otel-stack

OpenTelemetry for **Claude Code** and **GitHub Copilot**: enablement per surface, a
redaction-first collector config, and checks that run without a collector.

> [!CAUTION]
> **Eleven ways a working-looking setup gives you wrong or missing data. None of
> them error.**

## Verify your build

```sh
just smoke          # what Claude Code actually emits here — no collector, two prompts
just copilot-smoke  # what Copilot's exporter actually does — no seat, no calls
```

`just smoke` runs `claude -p` twice, so it makes two billed calls and writes a
session transcript to `~/.claude/projects/` like any other run. Only the OTel
output goes to a temp dir, which is deleted.

`just copilot-smoke` costs nothing and needs no sign-in: Copilot ships built into
VS Code, so its exporter is read straight off disk.

Claims below are pinned to Claude Code **v2.1.220** and verified **2026-09-12**;
`just smoke` re-verifies them on whatever you are running.

## Three producers, two of them called Copilot

| | Claude Code | Copilot — VS Code | Copilot — CLI |
|---|---|---|---|
| Metric namespace | `claude_code.*` | `copilot_chat.*` | `github.copilot.*` |
| Cost metric | ✅ | ❌ | ❌ |
| Billing attrs on spans | n/a | ❌ none | ✅ `nano_aiu` |
| Exports to `http://` | ✅ | ✅ | ❌ **refuses on v1.0.80+** — unreproduced, trap 2 |
| Cache-hit rate from | **metrics** | **traces only** | **traces only** |

VS Code also runs an **agent host process** alongside the chat extension; managed
telemetry applies to both, and it has its own confirmed `chat.agentHost.otel.*`
namespace — see [docs/04-surfaces.md](docs/04-surfaces.md).

Copilot ships **built into VS Code**, so its settings schema and its exporter
code are readable on disk with no seat. Copilot claims here are pinned to
copilot-chat **0.60.0** / VS Code **1.132.0** and verified **2026-09-21**;
`just copilot-check` re-verifies them on your install.

## The eleven traps

| # | Symptom | Cause | Fix |
|---|---|---|---|
| [1](#1-no-default-protocol) | Nothing arrives, no error | `OTEL_EXPORTER_OTLP_PROTOCOL` has no default and throws | Set it explicitly |
| [2](#2-the-copilot-cli-refuses-http) | VS Code data arrives, CLI data never does | CLI silently drops `http://` endpoints — **v1.0.80+, unreproduced** | TLS, or check your CLI version first |
| [3](#3-delta-versus-cumulative) | Dead for 60 s, then wrong counters | `delta` default, 60 s interval | `cumulative`, 10 s |
| [4](#4-two-identifiers-you-cannot-turn-off) | Team emails in your TSDB, permanently | `user.email` has no kill switch | The collector |
| [5](#5-response-logging-turns-itself-on) | Model output exported after an upgrade | `OTEL_LOG_ASSISTANT_RESPONSES` inherits the prompt flag | Set it to `0` |
| [6](#6-nano_aiu-is-duplicated-onto-children) | Copilot cost roughly doubled | `nano_aiu` is stamped on parent *and* children | Root span only |
| [7](#7-copilot-has-no-cost-metric) | No Copilot cost at all | Copilot emits none | Usage Metrics API |
| [8](#8-the-file-exporter-writes-empty-spans) | A big file of valid JSON, zero traces in it | `JSON.stringify` hits a circular span reference; the `catch` writes `{}` | Never `outfile` for traces — `enabled` **+** `dbSpanExporter` |
| [9](#9-the-endpoint-variable-is-an-on-switch) | Copilot exporting when you only configured Claude Code | `OTEL_EXPORTER_OTLP_ENDPOINT` alone enables Copilot's OTel | Know it is a switch, not just a destination |
| [10](#10-a-typo-in-the-endpoint-sends-data-to-localhost) | A remote endpoint configured, nothing ever arrives | `new URL()` throws, the catch falls back to `localhost:4318` | Check `enabledVia` in the Copilot Chat log |
| [11](#11-the-protocol-setting-and-the-variable-disagree) | `protocol: "grpc"` set, `http/json` on the wire | The setting feeds the protocol only; the env var also feeds transport | Use `exporterType: otlp-grpc` |

### 1. No default protocol

Claude Code throws `Unknown protocol set in … env var: undefined` and exports
nothing. [`monitoring-usage`][cc-mon] is explicit: *"Claude Code has no default
protocol, so set this or the signal-specific protocol variable for each `otlp`
exporter you enable."*

### 2. The Copilot CLI refuses `http://`

Export is dropped *"rather than sent in cleartext; startup is not aborted"* — no
warning, no non-zero exit ([copilot-cli#4567][cli4567], open as of 2026-09-12,
**reported against CLI v1.0.80**). **The VS Code extension exports to the same
endpoint fine**, so one collector on `localhost:4318` collects half your data
silently. Workarounds: [`otel/env/copilot-cli.env`](otel/env/copilot-cli.env).

> [!WARNING]
> **This is the one trap here that has never been reproduced.** It is
> vendor-reported, not observed. On the CLI runtime installed on this machine —
> v1.0.54, which predates the version the issue was filed against — the refusal
> is absent and the runtime's **own `copilot help monitoring` text recommends an
> `http://` endpoint as its first worked example**.
>
> `just copilot-smoke` reads whatever runtime you have and says which of those
> you are looking at. Treat the trap as version-bounded: still the first thing
> to check when CLI data is missing, not a fact about every build.

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

### 8. The file exporter writes empty spans

Set `github.copilot.chat.otel.outfile` and every span line on disk is the literal
two-byte string `{}`. The exporter serialises with a hand-rolled `JSON.stringify`
in a `try`/`catch` that returns `{}`; the span reaches its own
`BatchSpanProcessor` through the provider's span-processor chain, and that
processor holds a reference back to itself, so the stringify throws
`Converting circular structure to JSON` every time and the catch swallows it.

`outfile` — not `exporterType` — is the trigger. `exporterType: "file"` with no
`outfile` writes nothing and falls back to OTLP on `localhost:4318`.

Logs and metrics survive, but in the SDK's internal shape rather than OTLP/JSON,
and all three signals land in **one file with no type discriminator**.

**`{}` is valid JSON**, which is what makes this a trap rather than a bug you
notice: a record-counting check reports a file of nothing as tens of thousands of
healthy records. `grep -c '^{}$'` is the honest count, and
`just copilot-smoke <dump>` runs it for you.

The sink to use instead is `dbSpanExporter.enabled` — **together with**
`enabled: true`, because on its own it replaces your span exporter with one that
silently drops everything. Full detail in
[docs/02-copilot.md](docs/02-copilot.md).

### 9. The endpoint variable is an on switch

`OTEL_EXPORTER_OTLP_ENDPOINT` does not merely tell Copilot Chat *where* to
export. Its presence in the environment **enables export**, with no
`github.copilot.chat.otel.enabled` set anywhere:

```js
a = policyEnabled ?? COPILOT_OTEL_ENABLED ?? settingEnabled ?? o ?? !!e.OTEL_EXPORTER_OTLP_ENDPOINT
```

So exporting that variable for Claude Code — which needs
`CLAUDE_CODE_ENABLE_TELEMETRY=1` before it treats the same variable as anything
at all — quietly turns Copilot on too, pointed at the same collector. One
variable, two harnesses, opposite semantics.

The extension records which path enabled it. `enabledVia: "otlpEndpointEnvVar"`
in the **GitHub Copilot Chat** output channel means this is what happened to you.

### 10. A typo in the endpoint sends data to localhost

The endpoint is parsed with `new URL()` inside a `try`, and the `catch` returns
nothing:

```js
function YNi(n, e) { try { let r = new URL(t); return e === "grpc" ? r.origin : r.href } catch { return } }
g = YNi(A, d) ?? "http://localhost:4318"
```

A malformed value does not warn and does not abort. It falls back to
`http://localhost:4318`, where on most machines nothing is listening — so a
mistyped remote collector looks exactly like a correctly configured one that
happens to be quiet.

### 11. The protocol setting and the variable disagree

`github.copilot.chat.otel.protocol` advertises `grpc` in its enum. Setting it to
`grpc` gives you `http/json`.

```js
d = (… ?? OTEL_EXPORTER_OTLP_PROTOCOL ?? COPILOT_OTEL_PROTOCOL ?? (settingExporterType…)) === "grpc" ? "grpc" : "http"
p = policyProtocol ?? OTEL_EXPORTER_OTLP_PROTOCOL ?? COPILOT_OTEL_PROTOCOL ?? settingProtocol
m = d === "grpc" ? "grpc" : p === "http/protobuf" ? "http/protobuf" : "http/json"
```

`settingProtocol` reaches only `p`. The **environment variable of the same name
also reaches `d`**, the transport selector. With `exporterType: otlp-http`, `d`
is `"http"`, so `m` can only be `http/protobuf` or `http/json` — the setting's
own advertised value is unreachable.

`OTEL_EXPORTER_OTLP_PROTOCOL=grpc` works. The identically-named setting does not.
Select gRPC with `exporterType: otlp-grpc`.

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
| [`docs/01-claude-code.md`](docs/01-claude-code.md) | Enablement, the eight metrics, events, beta traces |
| [`docs/02-copilot.md`](docs/02-copilot.md) | Five surfaces, two engines, span hierarchy |
| [`docs/03-privacy.md`](docs/03-privacy.md) | What leaves the machine, and what cannot be turned off |
| [`docs/04-surfaces.md`](docs/04-surfaces.md) | Claude Code vs Copilot-VS Code vs Copilot-CLI, side by side |
| [`docs/05-normalization.md`](docs/05-normalization.md) | Joining the three shapes — and what cannot be joined |
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
| `tools/lib/common.sh` · `lib/report.py` | Shared helpers; the two halves print identical glyphs |
| `justfile` · `lefthook.yml` | `just check` runs every gate; lefthook runs it pre-commit |

Every tool is written in exactly one language, chosen by what it does: the gates
that parse structure are Python, the gates that orchestrate other binaries are
shell. Nothing embeds one language inside the other, because a heredoc body is
invisible to both linters.

## Status

v1 ships docs, configs and checks — no running stack. Compose, dashboards and a
Helm values file come next.

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
