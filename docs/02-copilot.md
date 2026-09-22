# GitHub Copilot

Verified **2026-09-21** against the shipping build: **copilot-chat 0.60.0**, host
**VS Code 1.132.0**. Config lives in
[`../otel/env/copilot-cli.env`](../otel/env/copilot-cli.env) and
[`../otel/env/copilot-vscode.env`](../otel/env/copilot-vscode.env).

> [!IMPORTANT]
> **Copilot is a built-in extension of VS Code, not a marketplace install.** Its
> full settings schema and its bundled exporter code sit inside the application
> bundle, readable with no seat and no sign-in. That is how everything below was
> verified, and it is what `just copilot-check` and `just copilot-smoke` read.

> [!CAUTION]
> **Static verification is not live traffic.** The settings schema and the
> exporter implementation are read from the shipped build and are facts. Two
> claims here are not, and neither has been observed: the ≥ 1.130 billable-span
> regression ([#328393][vs328393], a third-party report) and content exported
> despite `captureContent: false` (see [03-privacy.md](03-privacy.md)). Both
> need a signed-in session to settle.
>
> Static reading is not infallible either. Two claims here were once wrong
> because a grep matched something *adjacent* to the thing being claimed — a log
> tag mistaken for a settings namespace, and a retention routine missed entirely.
> Anchor on the code that runs, not on a string that resembles it.

## It is five surfaces over two engines

Not three parallel implementations — two instrumentation engines behind five
entry points. The engine matters more than the branding: anything running the CLI
runtime inherits the CLI's behaviour, including how it treats managed telemetry
headers on a cleartext endpoint — see below.

| Surface | Engine | Configured by |
|---|---|---|
| VS Code Copilot Chat | own instrumentation | `github.copilot.chat.otel.*` |
| VS Code **agent host** | CLI runtime as a stdio child | none of its own — it relays, see below |
| Copilot CLI | CLI runtime | `COPILOT_OTEL_*` env |
| Copilot SDK | wraps the CLI runtime | `TelemetryConfig` → env |
| Copilot desktop | CLI runtime, embedded | env only |

Managed telemetry is documented as applying to *"both the Copilot Chat extension
and the agent host process"*, which is only worth saying if they are separately
configurable. They are not: **the agent host has no settings namespace of its
own.** `chat.agentHost.otel.*` does not exist — zero occurrences in the agent
host, the extension bundle or `package.json`. A grep for `agentHost.otel`
matches `[agentHost-otel]` log tags and an `agentHostOTelService` DI brand,
which is how that claim gets made.

Concretely, it binds its own **in-process OTLP receiver on loopback**:

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

Its telemetry therefore follows the extension's configuration, and the `http://`
on that hop is internal to one process tree.

## The `http://` refusal, and what it is actually about

> [!CAUTION]
> **[copilot-cli#4567][cli4567] says the CLI silently disables export to any
> `http://` endpoint. The binary does something narrower.** The issue is widely
> cited; what follows is read from the shipped runtime.

There are **four** Copilot CLI runtimes reachable on a typical machine, and the
newest is not where you would look first:

| Location | Version |
|---|---|
| `~/.copilot/pkg/<platform>/<version>/app.js` | 0.0.372, 0.0.396, **1.0.54** |
| inside the extension, `node_modules/@github/copilot` | **1.0.73** |

The 1.0.73 native runtime is where the cleartext logic lives, and it says:

> *"Managed OTLP headers are configured but the managed telemetry endpoint '…'
> is not https; refusing to transmit the (sensitive) managed headers over
> cleartext."*
>
> *"Managed OTLP headers are configured but no managed telemetry endpoint is
> set; refusing to stamp the (sensitive) managed headers onto an endpoint
> resolved from the user-controlled `OTEL_EXPORTER_OTLP_ENDPOINT` / per-signal
> env vars."*

**What is refused is the credential, not the telemetry.** The CLI declines to
put enterprise-managed headers on an endpoint that is either cleartext or
user-controlled. Export itself proceeds. An individual developer with no managed
telemetry sees no change at all, and 1.0.54's own help text still lists
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` as its first worked example.

For an enterprise this still bites, just differently: telemetry arrives at the
collector **without the auth headers**, which reads downstream as unauthenticated
traffic rather than as missing data.

The same runtime exposes the way out, which the old advice to "terminate TLS in
front of the collector" never mentioned because it was not known:

```
OTEL_EXPORTER_OTLP_CERTIFICATE         # private CA for the collector
OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE  # mTLS
OTEL_EXPORTER_OTLP_CLIENT_KEY
```

plus per-signal `OTEL_EXPORTER_OTLP_{TRACES,METRICS}_*` variants. A private CA
is deliverable to the CLI.

> [!NOTE]
> **No code path was found in any local runtime that drops export purely because
> the scheme is `http`.** If CLI data is missing and you have no managed
> telemetry, this is not your cause. `just copilot-smoke` reports what your
> installed runtimes contain.

**Do not use the file exporter as a workaround** — read the next section first.

## The file exporter writes `{}` for every span

> [!CAUTION]
> **The file exporter produces a file full of valid JSON containing no traces at
> all.** Every span line is the literal two-byte string `{}`. Derived from the
> shipped copilot-chat **0.60.0** bundle by reading the serialiser and the object
> it is handed — structural, not observed in a live session.

**The trigger is `outfile`, not `exporterType`.** The file branch requires both:

```js
if (e.exporterType === "file" && e.fileExporterPath) { …FileSpanExporter… }
```

`fileExporterPath` comes from `outfile`, and an empty string becomes `undefined`.
So `exporterType: "file"` **on its own does not write a file** — every branch
falls through and telemetry goes to the default OTLP endpoint,
`http://localhost:4318`, where on most machines nothing is listening. Setting
`outfile` is what selects the file exporter, and it does so whatever
`exporterType` says.

The exporter serialises with a hand-rolled `JSON.stringify` wrapped in
`try { … } catch { return "{}" }`. The span object holds a live back-reference to
its own `BatchSpanProcessor`, whose `_shutdownOnce` holds a `BindOnceFuture`
whose `_that` points back at the processor. `JSON.stringify` throws
`Converting circular structure to JSON`, the catch swallows it, and `{}` is
written. No name, no trace ID, no attributes.

Logs and metrics **do** serialise — but into the SDK's internal shape
(`resource._rawAttributes` tuples, no `resourceLogs` envelope), which is not
OTLP/JSON, so no collector receiver reads it either.

All three signals share **one file** with no type discriminator, so telling them
apart means sniffing shape.

> [!WARNING]
> **`{}` is valid JSON**, so a record-counting inspector reports a file of
> nothing as tens of thousands of healthy records. Count the dead ones:
>
> ```sh
> grep -c '^{}$' spans.jsonl
> ```
>
> `just copilot-smoke` inspects the installed exporter, and
> `just copilot-smoke <path>` reports the composition of a dump you already have.

Two more properties of that exporter, independent of the serialisation bug:
`forceFlush()` is a literal `return Promise.resolve()` — a no-op that touches
neither the stream nor the disk — and there is **no rotation, no size cap and no
truncation**, so the file grows without bound. Spans contribute three bytes
each; the volume comes from logs and metrics.

All three exporters open their **own** append stream on the same path, so three
file descriptors write concurrently. `grep -c '^{}$'` is the honest count only
while no write interleaves mid-line.

> [!WARNING]
> **The replacement needs two settings, not one.** `dbSpanExporter.enabled` is
> the only span sink that runs in parallel with OTLP — but on its own it does
> the opposite of what you want:
>
> ```js
> t = e.dbSpanExporter && !e.enabledExplicitly && !e.fileExporterPath && e.exporterType !== "console"
> ```
>
> When `t` holds, the primary span exporter becomes a **null exporter** that
> drops every batch and reports `SUCCESS`, while logs and metrics are redirected
> to the console. `enabledExplicitly` is only true when `enabled` is set to
> `true` outright. So `dbSpanExporter.enabled` alone gives you SQLite and
> nothing else — with a reassuring `[OTel] Instrumentation enabled` line in the
> log and a successful export on every batch.
>
> Set **both**:
>
> ```jsonc
> "github.copilot.chat.otel.enabled": true,
> "github.copilot.chat.otel.dbSpanExporter.enabled": true
> ```

Do not repeat this check by grepping for `safeStringify`: that name is also
Ajv's code generator, which accounts for both of its occurrences in the bundle.
Anchor on the `catch` returning `{}` beside the write-stream construction.

## The three configuration traps live in the README

Traps **9** (the endpoint variable is an on switch), **10** (a malformed
endpoint silently reverts to `localhost:4318`) and **11** (the `protocol`
setting cannot select grpc, while the identically-named environment variable
can) are documented in full — with the resolver code they were read from — in
the [README](../README.md#the-eleven-traps) rather than repeated here.

They are all consequences of one function, `dqe()` in the shipped bundle, which
resolves policy, environment and settings into the config the exporter uses.
Read them together; individually each looks like an oddity, together they are a
precedence chain.

## The SQLite span store

`dbSpanExporter.enabled` writes to `agent-traces.db` in the extension's global
storage. It is the only durable local copy of a span when the collector was not
running, which makes it the obvious thing to replay from — so it is worth being
precise about what it does and does not hold.

Schema, read out of the shipped 0.60.0 bundle's own DDL rather than transcribed:

```sql
spans(span_id PK, trace_id, parent_span_id, name,
      start_time_ms INTEGER, end_time_ms INTEGER,
      status_code, status_message, operation_name, provider_name, agent_name,
      conversation_id, request_model, response_model,
      input_tokens, output_tokens, cached_tokens, reasoning_tokens,
      tool_name, tool_call_id, tool_type, chat_session_id, turn_index, ttft_ms REAL)
span_attributes(span_id FK, key, value TEXT, PK(span_id, key))
span_events(id PK, span_id FK, name, timestamp_ms, attributes TEXT)
schema_version(version INTEGER PRIMARY KEY)
CREATE VIEW sessions AS …  -- derived from spans; there is no sessions table
```

**`cached_tokens` is a column here**, which matters: cache-hit rate is otherwise
traces-only ([#317837][vs317837]), and this is the one place it is queryable
with SQL.

> [!IMPORTANT]
> **The store is lossy relative to OTLP.** "Replay the spans" conceals four
> things it cannot give back:
>
> | Loss | Consequence |
> |---|---|
> | Times are **milliseconds** | OTLP is nanoseconds. Sub-millisecond detail is gone |
> | **No resource** | `service.name` and every resource attribute must be synthesised |
> | **No instrumentation scope** | A replayed span cannot say which library emitted it |
> | `span_attributes.value` is **TEXT** | Ints, bools and arrays come back as strings |
>
> A replay therefore **reconstructs** spans; it does not restore them. For cost
> and token work that is fine. It is not fine to let the result look like
> observed data.

**Anything replayed from here must be marked** — `agent_otel.backfilled=true`,
the source database, and the replay time — so a dashboard can segment or exclude
it. Deciding that now is deliberate: the alternative is discovering after a
month of mixed data that no query can separate reconstruction from observation.

`just copilot-traces` reads the store read-only and reports schema version, span
count, date range, operations, and **which columns are actually populated** —
a `cached_tokens` column that is entirely NULL is the difference between having
that data and only appearing to. It also compares the store's columns against
the installed bundle's DDL, so the two cannot drift apart unnoticed.

**Retention is 7 days.** The store runs `DELETE FROM spans WHERE start_time_ms < ?`
on open, with a window of `10080*60*1e3` — 10,080 minutes, exactly seven days —
alongside a most-recent-100-sessions bound. That is the hard ceiling on how far
back any replay can reach.

## VS Code settings

All eleven keys, prefix `github.copilot.chat.otel.`, every one tagged `advanced`.

| Setting | Type | Default | Values and notes |
|---|---|---|---|
| `enabled` | bool | `false` | Requires window reload — as do all ten below |
| `exporterType` | string | `otlp-http` | `otlp-http`, `otlp-grpc`, `console`, `file` |
| `protocol` | string | `""` | `""`, `http/json`, `http/protobuf`, `grpc`. **Empty means `http/json`** |
| `otlpEndpoint` | string | `http://localhost:4318` | Base URL; the exporter appends the signal path |
| `captureContent` | bool | `false` | **Not reliably enforced**, see [03-privacy.md](03-privacy.md) |
| `headers` | object | `{}` | `{ "key": "value" }` onto the OTLP exporter. **Contains credentials** |
| `serviceName` | string | `""` | `service.name` resource attribute |
| `resourceAttributes` | object | `{}` | Extra resource attributes, merged per key with the env var |
| `maxAttributeSizeChars` | int | `0` | `0` **disables** truncation — see below |
| `outfile` | string | `""` | JSON-lines path. **Non-empty overrides `exporterType` to `file`** |
| `dbSpanExporter.enabled` | bool | `false` | SQLite span store. **Enables OTel by itself** |

Settings landed in **VS Code 1.119** (2026-05-06); `headers`, `protocol`,
`serviceName`, `resourceAttributes` and `maxAttributeSizeChars` arrived later.

`otlp-grpc` applies to the extension only. The CLI runtime uses HTTP regardless,
so selecting grpc does not change what the agent host does.

### Headers are a setting, not just an environment variable

`headers` takes a `{ "key": "value" }` object applied **directly to the OTLP
exporter**, not through the environment. It merges per key with
`OTEL_EXPORTER_OTLP_HEADERS`, and the environment wins on a collision.

This matters most on macOS, where a GUI-launched VS Code inherits launchd's
minimal environment rather than your shell's — an exported
`OTEL_EXPORTER_OTLP_HEADERS` is simply invisible unless you launch from a
terminal. The setting is read either way.

The cost is that settings.json is plaintext and often tracked in a dotfiles repo,
and `just leaks` scans `*.env` but not settings.json. Scope the token to ingest
only.

Precedence: enterprise policy → environment variable → user setting → default.

### Scope is `application` on all eleven

Workspace and folder settings **cannot** set them, which is the structural fix
for the pre-1.123.1 defect where a cloned repo could flip `enabled`,
`captureContent` or `otlpEndpoint` on you.

Five are described as "user settings only", meaning they take no *environment*
override of their own — but read that phrase carefully. `serviceName`,
`resourceAttributes` and `headers` still resolve an enterprise **policy** value,
and policy wins. Only `maxAttributeSizeChars` and `dbSpanExporter.enabled` have
no policy path at all.

### `maxAttributeSizeChars: 0` is not the safe value it looks like

`0` **disables** truncation, so a backend with a per-attribute size cap receives
the full JSON payload and may reject it. Set a positive value matching your
backend's limit. Truncated values are suffixed
`...[truncated, original N chars]`, so truncation is visible in the data rather
than silent.

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

`github.copilot.nano_aiu` is worse — canonical statement of the rule and its
caveats is [README trap 6](../README.md#6-nano_aiu-is-duplicated-onto-children).
In short: it is **stamped on the root and duplicated
onto every child**, so summing across spans double-counts outright. Read the root
only, and **divide by 1e9** — the unit is billionths of an AI unit.

`github.copilot.cost` is a per-request **model multiplier, not currency**.

Billing attributes are **CLI-runtime only**. VS Code Copilot Chat spans carry no
billing envelope at all.

## There is no cost metric

[copilot-cli#3778][cli3778] — a user-filed feature request, open as of
2026-09-12 — asks for parity with `claude_code.cost.usage`. Until then Copilot
cost comes from the Usage Metrics API, not OTel.

Compounding it, [copilot-cli#4224][cli4224] (closed 2026-09-20, fixed in CLI v1.0.86) reported that subagent spans
carry **no** `github.copilot.*` billing attributes and their spend is not folded
into the root either — roughly **10–15% of session cost invisible**.

## Do not trust telemetry from before

| Boundary | Effect |
|---|---|
| CLI < v1.0.64 | Cache and reasoning attributes used wrong underscore-separated names |
| CLI < v1.0.61 | JSON-only OTLP; `OTEL_EXPORTER_OTLP_PROTOCOL` silently ignored |
| VS Code < 1.123.1 | **Security**: workspace settings could flip `otel.enabled`/`captureContent`/`otlpEndpoint`. Fixed structurally — all eleven keys are `scope: application` in 0.60.0, so workspace settings cannot reach them |
| VS Code ≥ 1.130 | Session-ID attrs dropped; `chat` spans for billable models reportedly stopped ([#328393][vs328393], open) |

> [!WARNING]
> **The last row applies to this build.** 1.132.0 is ≥ 1.130, so this is a live
> hazard, not a historical one. Before you trust any VS Code dataset, **check
> that `gen_ai.request.model` matches the model you actually selected** — if
> recent builds emit spans only for utility models, your data contains no
> billable calls. This is one of the three claims that static verification
> cannot settle; it needs one signed-in request.

[cli4567]: https://github.com/github/copilot-cli/issues/4567
[cli3778]: https://github.com/github/copilot-cli/issues/3778
[cli4224]: https://github.com/github/copilot-cli/issues/4224
[vs317837]: https://github.com/microsoft/vscode/issues/317837
[vs328393]: https://github.com/microsoft/vscode/issues/328393
