# The local stack

```sh
just stack-init   # writes .env with a local dev token
just up           # brings it up, waits until every service is serving
just stack-check  # posts one span and proves it reaches Tempo
just down         # stop; `just down --volumes` also drops the agent's queue
```

Grafana on `http://127.0.0.1:3000`, anonymous admin, Pipeline Health provisioned.

## What it is for

Verifying that the configs in this repository work, on your machine, before you
point a real harness at them. **It is not a production deployment** and two
things make that explicit: Grafana has no auth, and the agent→gateway hop is
plain HTTP inside the compose network.

What it *does* share with a real deployment is the thing that matters — both
collectors mount `otel/collector-agent.yaml` and `otel/collector-gateway.yaml`
directly. Nothing is duplicated into `compose.yaml`. If those files are wrong,
the stack fails to start.

## The topology, and why there are two collectors

```
producer ──▶ collector-agent ──▶ collector-gateway ──┬─▶ prometheus
 (host)       durable queue        fan-out           ├─▶ loki
                                                     └─▶ tempo ──▶ grafana
```

The agent is the half that has to survive a laptop: it queues to disk, retries
forever, and redacts before anything leaves. The gateway sits beside the
backends and deliberately carries no queue — the network between it and them
does not disappear for eight hours at a time.

Running both locally is what makes the durability claim testable rather than
aspirational:

```sh
just up
podman compose stop collector-gateway     # the far end goes away
# ... produce some telemetry ...
podman compose start collector-gateway    # it comes back
just stack-check                          # the backlog arrives
```

That is `retry_on_failure.max_elapsed_time: 0` and a `file_storage`-backed
`sending_queue` doing their job. With the collector defaults — 300s and an
in-memory queue — the same test loses data, silently.

## Images are pinned by digest

A tag is mutable; a digest is the artefact. Each image carries a `# renovate:`
comment recording the human-readable version beside its digest, so the pin is
legible and updatable without being trusted.

## The collector's own metrics have no `_total` suffix

Every panel in Pipeline Health was written against
`otelcol_receiver_accepted_spans_total` and every one of them was empty. The
names this collector actually exposes are:

```
otelcol_receiver_accepted_spans        # not ..._total
otelcol_exporter_queue_size
otelcol_exporter_queue_capacity
otelcol_processor_memory_limiter_accepted_spans
```

A dashboard querying the `_total` form renders as a flat zero, which is
indistinguishable from a healthy pipeline with nothing to report. Confirm
against `curl -s localhost:9090/api/v1/label/__name__/values` on your own
collector version before trusting any panel — the suffix has moved between
collector releases and the upstream metric-name migration
(`_`-delimited to `.`-delimited) is still in flight.

Also note that failure counters do not appear until they are non-zero:
`otelcol_exporter_send_failed_spans` is absent on a healthy stack, so "no such
metric" and "no failures" look the same from a query.

That hazard was written here for days before anything acted on it. Measured
against a running stack, **three of the six Pipeline Health panels rendered "No
Data" while the pipeline was working perfectly** — Dropped before the queue,
Export failures by signal, and Memory limiter refusals. A blank panel reads as
"broken query", so the healthy state was indistinguishable from a broken
dashboard.

The `+` chain was worse than cosmetic. In PromQL a binary operation with an
empty operand evaluates to *empty*, so "Dropped before the queue" —
`sum(spans) + sum(log_records) + sum(metric_points)` — went blank whenever any
one of the three had never failed. A real span drop would have been hidden by
the panel whose only job is to show drops.

Every failure-counter expression is now guarded with `or on() vector(0)`, and
each term of a sum is guarded separately. `just dash-check` counts guards
against failure metrics and fails when a sum is only partly covered, because one
guard on a three-term chain still blanks.

`on()` is load-bearing and was measured both ways. Without it the match is on
the full label set, so `vector(0)` does not match a labelled series and is
*added* beside the real ones — three series where two belong.

## Two traps this stack itself can fall into

**Prometheus needs `--web.enable-otlp-receiver`.** Without it the gateway's POST
to `/api/v1/otlp` returns 404, the gateway's retry queue fills, and every
service still reports healthy. The failure presents as "Prometheus is up".

**Tempo returns HTTP 200 while discarding.** Ingestion limits are enforced
asynchronously, after the distributor has already acknowledged the write. The
config here sets `log_discarded_spans.enabled` so a discard is at least visible
in the logs rather than purely in a counter.

Loki is configured with `reject_old_samples_max_age: 720h` for a related
reason: anything replayed from a backlog is *old by definition*, and too narrow
a window turns "we recovered the data" into "we recovered the data and Loki
threw it away".

Mind the unit when you set it: Loki's default is `1w`, which is **168h**. A
"widened" window of 168h is the default written longhand and changes nothing.
Check the number against the default, not against your assumption of it.

## On this machine: podman cannot see `/Volumes`

Verified, not folklore:

```
$ podman run --rm -v "$PWD/otel:/cfg:ro" alpine ls /cfg     # repo on an external volume
Error: statfs .../otel: no such file or directory
```

(The same command run from a copy under `$HOME` succeeds — that is the whole
difference.)

The podman machine mounts the home volume, not external ones. If this repo
lives on an external disk, bind mounts fail and the stack will not start. Two
ways out:

1. **Run it from a copy under `$HOME`** — what the verification for this
   feature did:
   ```sh
   cp -R <repo> ~/agent-otel-stack && cd ~/agent-otel-stack && just up
   ```
2. **Give the machine the mount** — `podman machine stop`, then
   `podman machine set --volume /Volumes/T9:/Volumes/T9`, then start. More
   invasive; it recreates machine configuration.

This is a property of this machine, not of the compose file. On Linux with
Docker, or with the repo under `$HOME`, neither step is needed.

## When something does not come up

`just up` deliberately fails rather than returning 0 with a broken stack — it
polls each service's readiness endpoint and reports which one never answered.

- `just logs collector-agent` — config errors surface here immediately; the
  collector refuses to start on an unknown component rather than degrading.
- `OTEL_GATEWAY_TOKEN` unset → the agent exits at once, by design. Run
  `just stack-init`.
- Port already bound → everything binds to `127.0.0.1` only; check for another
  collector on 4317/4318.

## What it does not include

No Helm values, no TLS between agent and gateway, no Ops or Cost dashboard.
Pipeline Health comes first because it is the one that tells you whether the
other two are showing you anything at all.
