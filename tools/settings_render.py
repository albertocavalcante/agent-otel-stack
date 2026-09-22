#!/usr/bin/env python3
"""Render otel/env/claude-code.env as a settings.json `env` block. `just settings`.

Claude Code is configured two ways: environment variables, or an `env` object in
~/.claude/settings.json. Only the second survives a new shell, and it is the one
anybody actually wants. Until this existed the repository shipped the variables
in shell `KEY=value` syntax under a header saying "paste into the `env` block" —
leaving every reader to hand-convert twelve lines into JSON, get the quoting
wrong, and find out from a parse error. The Copilot file, for a surface nobody
can configure by environment variable at all, handed over ready-to-paste JSON.
The primary harness had the harder path.

The env file stays the single source of truth. This reads it; it does not carry
its own copy of the settings, because a second copy is a second thing to drift.

Prints JSON on stdout and guidance on stderr, so `just settings > block.json`
yields a file with nothing in it but JSON.

WRITES NOTHING. Rendering a fragment is reversible and obvious; editing a
settings file this repository does not own is neither, and the merge would have
to reason about comments, existing keys and JSONC. Paste it yourself.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import report  # noqa: E402

GATE = "settings"
ENV_FILE = "otel/env/claude-code.env"
TARGET = "~/.claude/settings.json"

# A live assignment. Anchored at both ends: a trailing comment or a quoted value
# is a form this parser has never seen in that file, and silently rendering it
# wrong is worse than refusing.
ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]*)=(\S*)$")

# A commented-out assignment — an option the file deliberately ships OFF.
# The same anchoring does load-bearing work here. Two lines in that file read
#     # OTEL_LOG_USER_PROMPTS=1 exports prompt text.
# and are prose ABOUT a setting, not the setting. A pattern that let trailing
# text through would turn the two most dangerous options in this repository on
# in anybody who passed --include-optional. Hence `\S*$`.
COMMENTED = re.compile(r"^#\s*([A-Z][A-Z0-9_]*)=(\S*)$")


def parse(text: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Split the file into live settings, commented-out settings, and refusals.

    Anything that is not blank, not a comment and not an assignment is returned
    as a refusal rather than skipped. A renderer that drops a line it does not
    understand is this repository's own subject matter: the caller pastes a
    block that looks complete and is missing the key that mattered.
    """
    live: dict[str, str] = {}
    optional: dict[str, str] = {}
    unparsed: list[str] = []

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if m := COMMENTED.match(line):
                optional[m.group(1)] = m.group(2)
            continue
        if m := ASSIGN.match(line):
            live[m.group(1)] = m.group(2)
        else:
            unparsed.append(f"line {n}: {raw}")

    return live, optional, unparsed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--include-optional",
        action="store_true",
        help="also emit the settings the env file ships commented out "
        "(today: the traces beta pair). Read why they are off first.",
    )
    args = ap.parse_args()

    root = report.enter_repo_root()
    path = root / ENV_FILE
    if not path.is_file():
        report.die(GATE, f"{ENV_FILE} is missing — nothing to render from")

    live, optional, unparsed = parse(path.read_text())

    if unparsed:
        for u in unparsed:
            report.note(u)
        report.die(
            GATE,
            f"{len(unparsed)} line(s) in {ENV_FILE} are not assignments and were not "
            "rendered — teach the parser this form rather than shipping a partial block",
        )
    if not live:
        report.die(GATE, f"{ENV_FILE} yielded no settings at all")

    env = dict(live)
    if args.include_optional:
        env.update(optional)

    # Every value is a string. Claude Code reads this object as environment
    # variables, and a JSON number or boolean here is a type error at load, not
    # a coerced 1 or true.
    print(json.dumps({"env": {k: str(v) for k, v in env.items()}}, indent=2))

    # stderr, so redirecting stdout gives a clean file.
    out = sys.stderr
    print(f"\n✓ {GATE}: {len(env)} setting(s) from {ENV_FILE}", file=out)
    if optional and not args.include_optional:
        print(
            f"  · {len(optional)} optional setting(s) withheld: {', '.join(sorted(optional))}\n"
            "    `just settings --include-optional` to include them.",
            file=out,
        )
    print(
        f"\n  Merge the `env` object into {TARGET}. If that file already has an\n"
        "  `env` block, merge INTO it — replacing it drops whatever else was there.",
        file=out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
