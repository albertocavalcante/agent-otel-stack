#!/usr/bin/env python3
"""Guide and VERIFY enabling Copilot on this account. `just copilot-enable`.

Fills, never submits.

There is no API for this. The Copilot REST API is entirely organisation and
enterprise seat administration under `/orgs/{org}/copilot/…`; a personal plan
can only be started in the web UI. Automating it would mean driving a browser
through a terms-of-service acceptance, which is a contract in your name and
belongs to your click, not to a script.

What a script CAN do is everything around that click, which is the part that
actually goes wrong. This reports the current entitlement, tells you exactly
what to do, then WATCHES until the account flips — so "I signed up" becomes an
observation rather than an assumption. The repository's whole argument is that
those are different things.

Read-only. No writes, no credential printed, and `--open` is opt-in.
"""

import argparse
import sys
import time
import webbrowser
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "lib"))

import copilot  # noqa: E402
import copilot_account  # noqa: E402
import report  # noqa: E402

GATE = "copilot-enable"

SIGNUP_URL = "https://github.com/settings/copilot"


def look() -> dict | None:
    """One entitlement read, or None if it could not be made."""
    token, _ = copilot_account.oauth_token()
    if token is None:
        return None
    try:
        status, body = copilot_account.fetch(token)
    except Exception:
        return None
    return body if status == 200 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--open", action="store_true", help=f"open {SIGNUP_URL} in a browser")
    ap.add_argument(
        "--watch",
        type=int,
        default=0,
        metavar="SECONDS",
        help="poll until chat is enabled, giving up after SECONDS",
    )
    args = ap.parse_args()

    body = look()
    if body is None:
        report.warn(GATE, "could not read the account's entitlement")
        report.note("run `just copilot-account` for why — it reports the credential state")
        return 1

    if body.get("chat_enabled"):
        report.ok(
            GATE, f"already enabled: {body.get('copilot_plan')} ({body.get('access_type_sku')})"
        )
        return next_steps()

    sku = body.get("access_type_sku")
    report.fail(GATE, f"chat is disabled on this account (sku: {sku})")

    if not body.get("can_signup_for_limited"):
        report.note("can_signup_for_limited is FALSE — Copilot Free is not offered to this")
        report.note("account. A paid plan or an org seat is the only route.")
        return 1

    print()
    report.note("Copilot Free IS available to this account. Two reported routes:")
    report.note(f"  1. {SIGNUP_URL} — enable it there")
    report.note("  2. sign in to Copilot inside VS Code; Free is said to be granted")
    report.note("     on sign-in for eligible accounts (reported, not verified here)")
    print()
    report.note("Either way it is YOUR acceptance of GitHub's terms. This tool does")
    report.note("not click it — it watches for the result.")

    if args.open:
        report.note(f"opening {SIGNUP_URL}")
        webbrowser.open(SIGNUP_URL)

    if not args.watch:
        print()
        report.note("re-run with --watch 300 to poll until the account flips")
        return 1

    print()
    report.note(f"watching for up to {args.watch}s — Ctrl-C to stop")
    deadline = time.monotonic() + args.watch
    while time.monotonic() < deadline:
        time.sleep(10)
        body = look()
        if body and body.get("chat_enabled"):
            print()
            report.ok(GATE, f"enabled: {body.get('copilot_plan')} ({body.get('access_type_sku')})")
            return next_steps()
        sys.stdout.write(".")
        sys.stdout.flush()

    print()
    report.fail(GATE, f"still disabled after {args.watch}s")
    return 1


def next_steps() -> int:
    """What must happen AFTER the seat exists, in order.

    Each of these has already silently cost this project time, so none of them
    is left implicit.
    """
    print()
    report.note("next, in order:")
    report.note("  1. RELOAD VS Code. The six otel settings sit behind")
    report.note("     _watchForReloadRequiredChanges — editing settings.json does")
    report.note("     nothing until the window reloads.")
    report.note("  2. send one AGENT-MODE request. Plain chat only produces `chat`")
    report.note("     spans; invoke_agent and execute_tool need agent mode.")
    report.note("  3. `just copilot-traces` — proves the span store was written.")

    # traces_db() returns None when the file has never been written, so the
    # absence branch must not interpolate it — "not written yet (None)" reads
    # like a bug in the tool rather than a fact about the machine.
    db = copilot.traces_db()
    print()
    if db is None:
        report.note("span store not written yet — expected, until step 2 happens")
    else:
        report.ok(GATE, f"span store exists: {db}")
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
