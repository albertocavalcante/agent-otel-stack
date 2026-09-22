# Entitlement: the surface is not the seat

Every other document here answers "is this configured correctly?". This one
answers the question that silently outranks it.

For eleven days this repository documented Copilot's telemetry surface in
detail, verified the eleven settings against the shipping bundle, paired
`dbSpanExporter.enabled` with `otel.enabled` so it would not install a null
exporter — and `agent-traces.db` never appeared. Not once.

The configuration was right the whole time. The account had no seat.

With no seat there are no requests. With no requests there are no spans. And
every surface-level check still reports ✓, because the surface really is fine —
`just copilot-check` reads a bundle that exists whether or not you can use it,
which is the same property that makes it work with no sign-in.

That is the gap `just copilot-account` closes.

## The three legs

| Gate | Reads | Answers |
|---|---|---|
| `just copilot-check` | the shipped VS Code bundle | do the documented settings still exist? |
| `just copilot-traces` | the local SQLite store | did any spans get written? |
| `just copilot-account` | the account's entitlement | **can this account produce spans at all?** |

Only the third needs the network and a credential, so like `just pins` it is
deliberately **not** part of `just check`.

## What it asks, and how

`GET https://api.github.com/copilot_internal/user` — the same endpoint the
editor plugins call before they can do anything. One read-only request about
your own account. The tool writes nothing and never prints the token or the
analytics tracking id.

The credential comes from `~/.config/github-copilot/apps.json`. Note what that
file is *not*: VS Code keeps its Copilot auth in the OS keychain, so this file
is usually written by whichever **other** client signed in last — copilot.lua,
the CLI, JetBrains. On the machine this was written on it belonged to
copilot.lua and was nine months old. It still answered correctly, because the
entitlement it reports is the *account's*, not the client's.

An absent or rejected credential is reported with `!`, not `✗`. A machine that
has never run a Copilot client is a legitimate state, and a gate that fails on
it teaches you to ignore the gate.

## The fields that matter

Measured on this account:

```
access_type_sku        : "subscription_ended"
copilot_plan           : "individual"
chat_enabled           : false
cli_enabled            : false
is_mcp_enabled         : false
assigned_date          : null
restricted_telemetry   : false
can_signup_for_limited : true
```

`chat_enabled` is the one that decides whether telemetry is possible.
`access_type_sku` tells you why.

The companion endpoint `/copilot_internal/v2/token` — the exchange every client
performs before its first request — returns **HTTP 403** with
`notification_id: subscription_ended`. That is the failure a user actually
experiences, and it happens before any OTel code runs.

Two fields worth reading even when they are boring:

- **`restricted_telemetry`** — enterprise policy can limit what an account may
  export, independently of whether it has a seat. Reported even when `false`,
  because "the field was absent" and "the field said no" are different answers.
- **`enterprise_list` / `organization_login_list`** — if either is non-empty,
  enterprise-managed telemetry settings **always** win over environment
  variables and user settings. See [02-copilot.md](02-copilot.md).

The response also carries per-SKU endpoints —
`https://proxy.individual.githubcopilot.com`, not the bare
`proxy.githubcopilot.com`. The bare host does not resolve; the subdomain is
chosen by plan.

## OpenTelemetry is not gated by SKU

Checked rather than assumed, by reading the 19.2 MB `copilot-chat` 0.60.0
bundle:

- All eleven settings are registered through the same generic helper as every
  other setting — `gn.OTelEnabled=pt("chat.otel.enabled",0,!1)`. No entitlement
  predicate, no SKU check.
- `access_type_sku` and `chat_enabled` appear **zero** times in the entire
  bundle, let alone near any of the 619 `otel` sites.
- The only entitlement-adjacent code anywhere near OTel does the opposite of
  gating: it converts quota state into **span attributes** — `entitlement`,
  `percent_remaining`, `overage_permitted`, `overage_count`, `reset_date`.
  Copilot *exports* your quota as telemetry.

So the export path is open on any plan that can make a request. What a plan
gates is the requests, not the instrumentation.

The limit of that claim: this is client-side evidence. It shows no gate in the
code that runs on your machine. It cannot prove the server behaves identically
for every SKU. The only complete test is one request.

## Copilot Free, as of 2026

`can_signup_for_limited: true` means Copilot Free is available to the account.

- **2,000 code completions per month.**
- **An allowance of GitHub AI Credits.** GitHub does not publish the Free
  number. Billing moved from "premium requests" to AI Credits on 2026-06-01, so
  the widely-quoted "50 chat requests per month" is pre-credits and should be
  treated as an order of magnitude, not a current figure.
- **Agent mode: included.**
- **Copilot CLI: included** — all plans have it.
- Auto model selection only.

Agent mode being included is the part that matters here, because the spans this
repository cares about are agent-shaped: `invoke_agent`, `chat`, `execute_tool`.
Chat alone would only ever produce the middle one.

## Two things found while checking

**The OTel settings require a window reload.** The extension registers
`_watchForReloadRequiredChanges` over exactly six of them — `OTelEnabled`,
`OTelExporterType`, `OTelOtlpEndpoint`, `OTelCaptureContent`, `OTelOutfile` and
`OTelDbSpanExporter`. Editing `settings.json` is not enough; VS Code must
reload before anything changes.

**There is a command to export the span store.**
`github.copilot.chat.otel.exportAgentTracesDB` copies `agent-traces.db` to a
path you choose, logging `[OTel] Exported agent-traces.db to …`. That is a
cleaner source for replay than reading the live database underneath a running
extension.

## What to do when it reports ✗

The gate tells you which of these you are in:

1. **`subscription_ended` with `can_signup_for_limited: true`** — sign up for
   Copilot Free, reload VS Code, send one agent-mode request.
2. **Credential rejected (401)** — sign in again from any Copilot client.
3. **No credential file** — the gate found nothing to ask with. It is not
   telling you the account has no seat; it is telling you it does not know.
