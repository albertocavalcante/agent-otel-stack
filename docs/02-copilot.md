# GitHub Copilot

Verified **2026-09-12**. Config lives in
[`../otel/env/copilot-cli.env`](../otel/env/copilot-cli.env) and
[`../otel/env/copilot-vscode.env`](../otel/env/copilot-vscode.env).

> [!CAUTION]
> **No Copilot seat was available while writing this.** Everything here is
> derived from vendor documentation and issue trackers, not observed. The Claude
> Code side has `just smoke`; this side has nothing equivalent.

## It is five surfaces over two engines

Not three parallel implementations — two instrumentation engines behind five
entry points. The engine matters more than the branding: anything running the CLI
runtime inherits the CLI's behaviour, including its refusal to export over
`http://`.

| Surface | Engine | Configured by |
|---|---|---|
| VS Code Copilot Chat | own instrumentation | `github.copilot.chat.otel.*` |
| VS Code **agent host** | CLI runtime in a utility process | unconfirmed — see [04-surfaces.md](04-surfaces.md) |
| Copilot CLI | CLI runtime | `COPILOT_OTEL_*` env |
| Copilot SDK | wraps the CLI runtime | `TelemetryConfig` → env |
| Copilot desktop | CLI runtime, embedded | env only |

Managed telemetry is documented as applying to *"both the Copilot Chat extension
and the agent host process"*. Whether the agent host needs its own settings
namespace is unconfirmed; what is certain is that it runs the CLI runtime, so the
CLI's `http://` refusal applies to it.

## The `http://` trap

> [!CAUTION]
> **The Copilot CLI silently disables export to any `http://` endpoint**,
> including `http://localhost:4318`. From `copilot help monitoring`: export is
> dropped *"rather than sent in cleartext; startup is not aborted."* There is no
> non-zero exit and the only signal is a process-log warning.
> ([copilot-cli#4567][cli4567], open as of 2026-09-12, reported against v1.0.80.)

**The VS Code extension exports to that same endpoint without complaint.** So a
collector on `localhost:4318` receives extension data and nothing from the CLI,
and the obvious conclusion — "the CLI has no telemetry" — is wrong.

Use TLS in front of the collector, or the file exporter.

## VS Code settings

| Setting | Default | Values |
|---|---|---|
| `github.copilot.chat.otel.enabled` | `false` | bool |
| `github.copilot.chat.otel.exporterType` | `otlp-http` | `otlp-http`, `otlp-grpc`, `console`, `file` |
| `github.copilot.chat.otel.otlpEndpoint` | `http://localhost:4318` | URL |
| `github.copilot.chat.otel.captureContent` | `false` | bool — **not reliably enforced**, see [03-privacy.md](03-privacy.md) |
| `github.copilot.chat.otel.maxAttributeSizeChars` | `0` | int; `0` = no truncation |

Landed in **VS Code 1.119** (2026-05-06). There is **no user-facing headers
setting** — auth headers come from `OTEL_EXPORTER_OTLP_HEADERS` in the
environment VS Code was launched from. Precedence: policy → env → user setting →
default.

`otlp-grpc` applies to the extension only. The CLI runtime uses HTTP regardless,
so selecting grpc does not change what the agent host does.

## Enterprise-managed export

Shipped 2026-07-08, **enterprise scope, not org**. A `telemetry` block covering
`enabled`, `endpoint`, `protocol`, `captureContent`, `lockCaptureContent`,
`serviceName`, `resourceAttributes`, `headers`. **A managed value always wins**
over environment variables and user settings.

Managed `protocol` accepts `http/json` or `http/protobuf` only — a third, narrower
value set than either of the two above.

## Traces, not metrics

**Cache tokens exist only on spans, on every surface.** `microsoft/vscode#317837`
([open as of 2026-09-12][vs317837]) puts it plainly: cached input *"is not
surfaced in metrics, so Prometheus/Grafana dashboards cannot calculate cache hit
rate or cached-input billing without trace parsing."*

The CLI's own docs agree — `gen_ai.client.token.usage` is *"token counts by type
(input/output)"*, with no cache dimension.

**Build trace-first.** There is no per-signal disable; OTel is global on or off.

Metric namespaces differ by surface: VS Code emits `copilot_chat.*`, the CLI
emits `github.copilot.*`. One dashboard cannot serve both.

## Span hierarchy — flat, and the parent already includes the children

```
invoke_agent          ← root; usage is "total input tokens (all turns)"
├── chat              ← siblings, NOT nested
└── execute_tool
```

> [!IMPORTANT]
> **Aggregate at exactly one level.** Use `chat` for per-model cost or
> `invoke_agent` for per-turn — never add them, because the root already contains
> the children.

`github.copilot.nano_aiu` is worse: it is **stamped on the root and duplicated
onto every child**, so summing across spans double-counts outright. Read the root
only, and **divide by 1e9** — the unit is billionths of an AI unit.

`github.copilot.cost` is a per-request **model multiplier, not currency**.

Billing attributes are **CLI-runtime only**. VS Code Copilot Chat spans carry no
billing envelope at all.

## There is no cost metric

[copilot-cli#3778][cli3778] — a user-filed feature request, open as of
2026-09-12 — asks for parity with `claude_code.cost.usage`. Until then Copilot
cost comes from the Usage Metrics API, not OTel.

Compounding it, [copilot-cli#4224][cli4224] (open) reports that subagent spans
carry **no** `github.copilot.*` billing attributes and their spend is not folded
into the root either — roughly **10–15% of session cost invisible**.

## Do not trust telemetry from before

| Boundary | Effect |
|---|---|
| CLI < v1.0.64 | Cache and reasoning attributes used wrong underscore-separated names |
| CLI < v1.0.61 | JSON-only OTLP; `OTEL_EXPORTER_OTLP_PROTOCOL` silently ignored |
| VS Code < 1.123.1 | **Security**: workspace settings could flip `otel.enabled`/`captureContent`/`otlpEndpoint` |
| VS Code ≥ 1.130 | Session-ID attrs dropped; `chat` spans for billable models reportedly stopped ([#328393][vs328393], open) |

> [!WARNING]
> The last row matters before you trust any VS Code dataset. **Check that
> `gen_ai.request.model` matches the model you actually selected** — if recent
> builds emit spans only for utility models, your data contains no billable
> calls.

[cli4567]: https://github.com/github/copilot-cli/issues/4567
[cli3778]: https://github.com/github/copilot-cli/issues/3778
[cli4224]: https://github.com/github/copilot-cli/issues/4224
[vs317837]: https://github.com/microsoft/vscode/issues/317837
[vs328393]: https://github.com/microsoft/vscode/issues/328393
