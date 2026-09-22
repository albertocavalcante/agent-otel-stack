#!/usr/bin/env python3
"""Report the Copilot entitlement on this account. `just copilot-account`.

The third leg. `copilot-check` reads the shipped bundle, `copilot-traces` reads
the local span store, and neither can see the one thing that silently stops
either from ever producing data: whether the account has a seat.

That gap cost this project real time. Every Copilot setting was correct, the
eleven keys were right, `dbSpanExporter` was paired properly — and
`agent-traces.db` still never appeared, because the subscription had ended. With
no seat there are no requests, with no requests there are no spans, and every
surface-level check still reports ✓ because the surface really is fine.

NETWORK, and a credential. Like `pins`, deliberately NOT in `just check`.

Read-only: one GET against the account's own entitlement, the same endpoint the
editor plugins call before they can do anything. Writes nothing, and never
prints the token or the analytics tracking id.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import report  # noqa: E402

GATE = "copilot-account"

# Where the Copilot plugins keep the user-to-server token. NOT where VS Code
# keeps one: VS Code uses the OS keychain, so this file is usually written by
# whichever OTHER client was configured last — copilot.lua, the CLI, JetBrains.
# The entitlement it reports is the ACCOUNT's, so any of them answers the
# question; the file just might be older than you expect.
CREDS = Path.home() / ".config/github-copilot/apps.json"

ENDPOINT = "https://api.github.com/copilot_internal/user"

# Never printed, whatever the API adds later.
SECRET = {"token", "analytics_tracking_id", "tracking_id", "nes_token"}


def oauth_token() -> tuple[str | None, str | None]:
    """Return (token, source-label), or (None, reason)."""
    if not CREDS.is_file():
        return None, f"{CREDS} does not exist — no Copilot client has signed in on this machine"
    try:
        data = json.loads(CREDS.read_text())
    except json.JSONDecodeError as exc:
        return None, f"{CREDS} is not valid JSON: {exc}"
    for host, entry in data.items():
        if isinstance(entry, dict) and entry.get("oauth_token"):
            return entry["oauth_token"], host
    return None, f"{CREDS} holds no oauth_token"


def fetch(token: str) -> tuple[int, dict | None]:
    req = urllib.request.Request(
        ENDPOINT,
        headers={
            "Authorization": f"token {token}",
            # The endpoint varies its response by client. Identify as the
            # surface this repository documents.
            "Editor-Version": "vscode/1.132.0",
            "Editor-Plugin-Version": "copilot-chat/0.60.0",
            "User-Agent": "GitHubCopilotChat/0.60.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, None


def main() -> int:
    token, source = oauth_token()
    if token is None:
        # Absent credentials are not a failure. A machine that has never run a
        # Copilot client is a legitimate state, and reporting ✗ for it would
        # train the reader to ignore this gate.
        report.warn(GATE, source or "no credential found")
        report.note("this reports nothing about the account — it found nothing to ask with")
        return 0

    report.note(f"asking as the credential stored for {source}")
    try:
        status, body = fetch(token)
    except (urllib.error.URLError, TimeoutError) as exc:
        report.die(GATE, f"could not reach {ENDPOINT}: {exc}")

    if status == 401:
        report.warn(
            GATE, "the stored credential is rejected (401) — it has expired or been revoked"
        )
        report.note("sign in again from any Copilot client, then re-run")
        return 0
    if status != 200 or body is None:
        report.die(GATE, f"unexpected HTTP {status} from {ENDPOINT}")

    sku = body.get("access_type_sku")
    plan = body.get("copilot_plan")
    chat = body.get("chat_enabled")
    cli = body.get("cli_enabled")
    can_free = body.get("can_signup_for_limited")
    restricted = body.get("restricted_telemetry")

    report.note(f"login {body.get('login')}  plan {plan}  sku {sku}")
    report.note(
        f"chat_enabled {chat}   cli_enabled {cli}   is_mcp_enabled {body.get('is_mcp_enabled')}"
    )

    orgs = body.get("organization_login_list") or []
    ents = body.get("enterprise_list") or []
    if orgs or ents:
        report.note(f"orgs {orgs}  enterprises {ents}")
        report.note("enterprise-managed telemetry ALWAYS wins over env vars and user settings")

    # Enterprise policy can restrict telemetry independently of the seat. It is
    # reported even when false, because "the field was absent" and "the field
    # said no" are the kind of distinction this repository exists to keep.
    if restricted:
        report.warn(
            GATE, "restricted_telemetry is TRUE — policy limits what this account may export"
        )
    else:
        report.note(f"restricted_telemetry {restricted}")

    if not chat:
        report.fail(GATE, f"chat is DISABLED on this account (sku: {sku})")
        report.note("no requests can be made, so no spans exist to export — the")
        report.note("OTel settings can be perfectly correct and still produce nothing")
        if can_free:
            report.note("can_signup_for_limited is true: Copilot Free is available to this account")
        return 1

    report.ok(GATE, f"chat is enabled on {plan} ({sku}) — this account can produce telemetry")
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
