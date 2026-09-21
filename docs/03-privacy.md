# What leaves the machine

Both harnesses default to **no prompt content**. Neither defaults to no identity.
Those are different guarantees and the gap between them is why
[`../otel/collector-agent.yaml`](../otel/collector-agent.yaml) exists.

## The two you cannot turn off

`user.email` and `organization.id` are attached to **every Claude Code metric and
every event** whenever you are authenticated. [`monitoring-usage`][mon]: *"Always
included when available."*

There is no environment variable, no settings key, and no managed setting that
removes them. The only options are: do not enable telemetry, or strip them
downstream.

> [!IMPORTANT]
> **This is the argument for running a collector.** Prometheus, Loki and Tempo
> all accept OTLP directly, and pointing the harnesses straight at them is
> simpler and saves ~350 MiB. It also means your team's email addresses are in a
> time-series database, permanently, by default.

Copilot's equivalent set — always on, no setting of its own, and surviving
`captureContent=false`:

- `github.copilot.git.repository` — **your remote URL**
- `github.copilot.git.branch`, `.commit_sha`
- `github.copilot.github.org`
- file paths and commands on VS Code tool spans

## Content gates

All default **off**. All are opt-in.

| Harness | Gate | Exposes |
|---|---|---|
| Claude Code | `OTEL_LOG_USER_PROMPTS` | prompt text |
| Claude Code | `OTEL_LOG_ASSISTANT_RESPONSES` | model output |
| Claude Code | `OTEL_LOG_TOOL_DETAILS` | tool inputs and parameters |
| Claude Code | `OTEL_LOG_RAW_API_BODIES` | **entire conversation, system prompt, all tool definitions** |
| Copilot | `captureContent` / `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | messages, system instructions, tool args and results |

### The one that turns itself on

> [!CAUTION]
> **`OTEL_LOG_ASSISTANT_RESPONSES` follows `OTEL_LOG_USER_PROMPTS` when unset.**
> Anyone who had prompt logging enabled began exporting model output on upgrade
> to 2.1.193, with no configuration change. Set it to `0` explicitly whenever you
> set prompt logging — [`../otel/env/claude-code.env`](../otel/env/claude-code.env) does.

### The one that means everything

`OTEL_LOG_RAW_API_BODIES` emits the full request and response JSON. Anthropic's
own wording: enabling it *"implies consent to everything `OTEL_LOG_USER_PROMPTS`,
`OTEL_LOG_TOOL_DETAILS`, and `OTEL_LOG_TOOL_CONTENT` would reveal."*

Concretely that is the system prompt, every message in the conversation, and all
tool definitions — so source code, credentials pasted into a prompt, and the
contents of any `.env` a tool read. Only extended-thinking content is always
redacted.

In `file:<dir>` mode the JSON is written with default permissions and **never
cleaned up**. Debug only; never in a default profile.

### Copilot's gate is not reliable

Three open defects report content escaping regardless of the setting:

| Issue | Claim |
|---|---|
| [vscode#307407][i307407] | `captureContent=false` still exports content attributes |
| [vscode#326254][i326254] | chat spans carry full prompts, system instructions, responses |
| [vscode#325720][i325720] | tool args and results export **unconditionally** |

Assume Copilot prompt content may leave the machine whatever the setting says.

## What the collector does about it

[`../otel/collector-agent.yaml`](../otel/collector-agent.yaml), in order:

1. **`attributes/scrub`** — deletes `user.email` and the Copilot git attributes;
   hashes `organization.id` and `user.account_uuid`.
2. **`redaction/content`** — deny-list over the content keys both harnesses can
   emit, plus value patterns for email addresses, Anthropic API keys and GitHub tokens.
3. **`attributes/metrics_cardinality`** — drops `session.id` from metrics only.

> [!WARNING]
> **Hashing is pseudonymisation, not anonymisation.** The digest is unsalted, so
> anyone holding your member list can compute it for every candidate and reverse
> the mapping in seconds. It stops casual reading and accidental egress; it does
> not defeat someone who wants the answer. For a real guarantee use the redaction
> processor's keyed `hmac-sha256`.

> [!NOTE]
> The `redaction` processor is **beta for traces and alpha for logs and metrics**.
> Two of the three pipelines depend on an alpha component.

## Before you enable anything

- Decide whether the backend is somewhere `user.email` would be acceptable if the
  scrub were mis-configured. Then configure the scrub anyway.
- `OTEL_EXPORTER_OTLP_HEADERS` is where a real token gets pasted. `just leaks`
  scans `*.env` for exactly that reason.
- On Copilot in VS Code that token can now live in **settings.json** instead
  (canonical: [02-copilot.md](02-copilot.md)),
  under `github.copilot.chat.otel.headers`. That file is plaintext, frequently
  tracked in a dotfiles repo, and **outside every gate in this repo**. Scope the
  token to ingest only.
- On a shared or enterprise machine, managed settings override everything you set
  — including the endpoint. Your telemetry may already have a destination.
- And on any machine, so does the ambient environment. `OTEL_EXPORTER_OTLP_ENDPOINT`
  **enables Copilot Chat's export by its presence alone** — no `enabled` setting
  required. Export it for Claude Code, which treats it as inert without
  `CLAUDE_CODE_ENABLE_TELEMETRY=1`, and you have switched on a second harness
  pointed at the same collector. See README trap 9.

[mon]: https://code.claude.com/docs/en/monitoring-usage
[i307407]: https://github.com/microsoft/vscode/issues/307407
[i326254]: https://github.com/microsoft/vscode/issues/326254
[i325720]: https://github.com/microsoft/vscode/issues/325720
