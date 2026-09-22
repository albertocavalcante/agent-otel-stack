# Joining the three shapes

Three producers, no shared schema. This is the part nobody has published, and it
is mostly a story about what **cannot** be joined.

Read [02-copilot.md](02-copilot.md) first — this page assumes it.

## What the same fact is called

| Fact | Claude Code | Copilot (both surfaces) |
|---|---|---|
| Input tokens | `claude_code.token.usage{type="input"}` | `gen_ai.usage.input_tokens` (span) |
| Output tokens | `claude_code.token.usage{type="output"}` | `gen_ai.usage.output_tokens` (span) |
| Cache read | `claude_code.token.usage{type="cacheRead"}` | `gen_ai.usage.cache_read.input_tokens` (span) |
| Cache write | `claude_code.token.usage{type="cacheCreation"}` | `gen_ai.usage.cache_creation.input_tokens` (span) |
| Model | `model` attribute | `gen_ai.request.model` |
| Cost | `claude_code.cost.usage` (USD) | **does not exist** |

Two structural differences make this harder than a rename.

**Claude Code puts the token type in a label; Copilot puts it in the metric
name.** One is `sum by (type)`, the other is four separate fields on a span. Any
common view has to pick one shape and convert into it.

**Claude Code's are metrics; Copilot's are span attributes.** There is no Copilot
metric carrying cache tokens at all ([vscode#317837][vs317837], open), so the
join cannot happen in PromQL — it has to happen before storage.

## Deriving Copilot metrics from spans

The collector's `spanmetrics` connector turns spans into metrics, which is the
only way to get Copilot cache data into the same store as Claude Code's.

```yaml
connectors:
  spanmetrics:
    # Only span-level attributes that are bounded. See the cardinality warning.
    dimensions:
      - name: gen_ai.request.model
      - name: gen_ai.operation.name
    histogram:
      explicit:
        buckets: [100ms, 1s, 10s, 60s]

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, attributes/scrub, redaction/content, batch]
      exporters: [otlp_grpc/tempo, spanmetrics]  # fan out
    metrics/from-spans:
      receivers: [spanmetrics]
      processors: [memory_limiter, batch]
      exporters: [otlp_http/prometheus]
```

> [!CAUTION]
> **Do not add `tool_name` or `query_source` as dimensions.** On Claude Code
> before 2.1.268 those carry raw MCP tool names and arbitrary subagent names,
> both unbounded — the bounded `*_safe` variants do not exist. On Copilot,
> `gen_ai.tool.name` is equally unbounded. A spanmetrics connector with an
> unbounded dimension recreates the cardinality bomb *inside* your metrics store,
> where it is far more expensive than in Tempo.

`spanmetrics` gives you call counts and duration. It does **not** sum arbitrary
attributes, so token totals still need either a transform processor or
querying Tempo directly with TraceQL.

## The aggregation trap, restated because it is the one that bites

Claude Code metrics are counters. Sum them.

Copilot spans are **not** summable across levels (canonical statement of this
rule: [README trap 6](../README.md#6-nano_aiu-is-duplicated-onto-children)). `invoke_agent` is the root and
its token counts already contain every child `chat` span. `github.copilot.nano_aiu`
is worse — it is duplicated onto the children outright.

```
# WRONG — double-counts every nested call
sum(gen_ai.usage.input_tokens)

# RIGHT — pick one level
sum(gen_ai.usage.input_tokens) where span.name == "chat"
```

And even the right version undercounts: subagent spans carry no billing envelope
and are not folded into the root either ([copilot-cli#4224][cli4224], closed 2026-09-20, fixed in v1.0.86),
losing roughly 10–15% of session spend.

## Cost cannot be normalised

This is the honest conclusion and the reason a single "spend" dashboard is not
achievable today.

| Producer | Cost source | Unit |
|---|---|---|
| Claude Code | `claude_code.cost.usage` | **USD** |
| Copilot CLI | `github.copilot.nano_aiu` ÷ 1e9, **root span only** | AI units |
| Copilot VS Code | not in telemetry at all | — |

Three separate problems stack up:

1. **Different units.** USD against AI units. There is no published conversion,
   and `github.copilot.cost` is a per-request *model multiplier*, not currency.
2. **One surface has nothing.** VS Code chat spans carry no billing attributes.
   This one is verified by *absence* — in the monitoring documentation, and in
   the shipped extension's attribute definitions. Absence is weaker evidence than
   presence; treat it as strong but not conclusive.
3. **Claude Code's figure is list price** unless an organisation has configured
   the `modelPricing` managed setting (2.1.243+), so it is not what a contracted
   customer actually pays either.

> [!IMPORTANT]
> **Do not build a cross-harness cost panel.** Build two, label the units, and
> put them side by side. A single number here would be a fabrication with a
> plausible shape — which is worse than an empty panel.

Copilot spend belongs on the Usage Metrics API, not in this pipeline.

## What does normalise cleanly

Three things, and they are worth having:

- **Token volume by type**, once Copilot spans are converted. Same units, same
  meaning, genuinely comparable.
- **Cache-read share** — `cacheRead / (input + cacheRead + cacheCreation)` on
  both sides, after conversion. This is the metric the whole exercise is for.
- **Latency and call counts**, via `spanmetrics` on Copilot and
  `claude_code.active_time.total` plus event timestamps on Claude Code.

Everything else is either producer-specific (`edit.survival.*` on Copilot,
`lines_of_code.count` on Claude Code) or blocked above.

## Recommended shape

One collector, three pipelines, **separate dashboards per producer** with a
fourth that shows only the three normalised series above.

Resist one unified dashboard. The metric namespaces differ, the cost story is
unbridgeable, and a panel that silently shows one producer's data while appearing
to show both is the failure this repo exists to prevent.

[vs317837]: https://github.com/microsoft/vscode/issues/317837
[cli4224]: https://github.com/github/copilot-cli/issues/4224
