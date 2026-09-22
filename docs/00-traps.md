# The twelve traps

Twelve ways a working-looking OTel setup gives you wrong or missing data. None
of them error; none of them appear in a log you would think to read.

Each is stated as what is true now. Several correct a claim that is widely
repeated elsewhere — including in this repository's own earlier drafts — and
where that matters the correction is the finding, not a footnote.

Back to the [README](../README.md).

### 1. No default protocol

Claude Code throws `Unknown protocol set in … env var: undefined` and exports
nothing. [`monitoring-usage`][cc-mon] is explicit: *"Claude Code has no default
protocol, so set this or the signal-specific protocol variable for each `otlp`
exporter you enable."*

### 2. The CLI refuses `http://` — for enterprise headers, not for export

What the refusal actually is, read from the CLI runtime bundled inside the
extension (`@github/copilot` **1.0.73**, native `runtime.node`):

> *"Managed OTLP headers are configured but the managed telemetry endpoint '…'
> is not https; refusing to transmit the (sensitive) managed headers over
> cleartext."*
>
> *"Managed OTLP headers are configured but no managed telemetry endpoint is
> set; refusing to stamp the (sensitive) managed headers onto an endpoint
> resolved from the user-controlled `OTEL_EXPORTER_OTLP_ENDPOINT`."*

So the CLI refuses to **attach enterprise credentials to a cleartext or
user-controlled endpoint**. It does not refuse to export. If you have no managed
headers — every individual developer — `http://localhost:4318` is unaffected,
and the runtime's own `copilot help monitoring` still lists it as the first
worked example.

> [!WARNING]
> **[copilot-cli#4567][cli4567] describes this as export being dropped. That is
> not what the binary does.** No code path in any local runtime drops export
> because the scheme is `http`. If your CLI data is missing and you have no
> managed telemetry configured, look elsewhere first — `just copilot-smoke`
> reports what your installed runtimes actually contain.

The same runtime exposes **mTLS and private-CA support** —
`OTEL_EXPORTER_OTLP_CERTIFICATE`, `..._CLIENT_CERTIFICATE`, `..._CLIENT_KEY`,
plus per-signal variants — which is the supported way to point it at an
`https://` collector you terminate yourself.

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
change. [`otel/env/claude-code.env`](../otel/env/claude-code.env) sets it explicitly.

### 6. `nano_aiu` is duplicated onto children

`github.copilot.nano_aiu` is stamped on the root `invoke_agent` span **and on
every child `chat` span**, so summing across spans double-counts. Read the root
only.

**The unit is billionths of an AI unit — divide by 1e9.** A dashboard that
plots it raw is wrong by a factor of a billion. And `github.copilot.cost` is a
per-request **model multiplier, not a currency value**.

> [!NOTE]
> We have not located a GitHub-authored page stating the duplication rule in
> those words, and it remains **unverified**.
>
> [copilot-cli#4224][cli4224] was previously cited here as corroboration. That
> was a misattribution: #4224 is about subagent spend being *omitted*, not about
> `nano_aiu` being *duplicated* — and it reports the root's `nano_aiu` as
> **equal to** the sum of main-agent chat spans, which is evidence against
> duplication in that dataset. It is cited correctly under trap 7.
>
> #4224 was also **closed 2026-09-20**, resolved in CLI v1.0.86.

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
[docs/02-copilot.md](02-copilot.md).

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

### 12. Prometheus renames every metric you send it

The names this repo documents are the names the harness emits. They are **not**
the names Prometheus stores. Its OTLP receiver normalises: dots become
underscores, counters gain `_total`, and **the unit is folded into the name**.

| Documented | Stored in Prometheus (unit folded in) |
|---|---|
| `claude_code.session.count` | `claude_code_session_count_total` |
| `claude_code.cost.usage` | `claude_code_cost_usage_USD_total` |
| `claude_code.token.usage` | `claude_code_token_usage_tokens_total` |
| `claude_code.active_time.total` | `claude_code_active_time_seconds_total` |

Observed live on 2026-09-22 by sending one real Claude Code session through the
stack. A panel written from the documented name renders as a flat empty graph —
no error, no "unknown metric", just nothing. Which is indistinguishable from a
harness that has not run.

> [!WARNING]
> **Two different normalisations coexist in the same Prometheus.** Metrics that
> arrive over OTLP get the treatment above. The collector's *own* telemetry is
> scraped from its Prometheus exporter and does **not** get `_total` — it is
> `otelcol_receiver_accepted_spans`, bare. So the rule you learn writing one
> dashboard is wrong for the other.

Check before you write, on your own versions:

```sh
curl -s localhost:9090/api/v1/label/__name__/values | jq -r '.data[]' | grep claude_code
```

A related non-bug worth knowing: with a **one-shot** workload, `rate()` and
`increase()` go empty about five minutes after the harness exits, because
Prometheus marks the series stale. The dashboard is correct; the data stopped.

[cc-mon]: https://code.claude.com/docs/en/monitoring-usage
[cli3778]: https://github.com/github/copilot-cli/issues/3778
[cli4224]: https://github.com/github/copilot-cli/issues/4224
[cli4567]: https://github.com/github/copilot-cli/issues/4567
