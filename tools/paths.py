#!/usr/bin/env python3
"""Fail if a comment points at a repo file that does not exist.

Run by `just paths`.

`just links` only parses markdown `](...)` syntax in `*.md`, so a bare path in a
shell comment, a Python constant or an env file is outside every other gate.
This repo shipped five pointers to an empty `docs/` directory that way, one of
them inside a runtime failure message.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import report

GATE = "paths"

# Anchored on a known extension so the false-positive rate stays near zero.
# The negative lookbehind is the load-bearing part: without it, an absolute path
# like /private/tmp/x.json matches from `private/` onward and reports a phantom
# relative path that was never written.
TOKEN = re.compile(
    r"(?<![A-Za-z0-9_./~-])([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+\.(?:md|ya?ml|json|sh|env|py))"
)

# `.py` is here because the gates that hold this repo's paths honest are now
# themselves Python. Without it, every path named in a gate's own source would
# stop being checked the moment it moved out of a shell heredoc.
SCAN_SUFFIXES = (".sh", ".env", ".yaml", ".yml", ".py")


def scanned_files() -> list[str]:
    """Every shippable file this gate reads, including untracked ones.

    `--others --exclude-standard` matters: a plain `git ls-files` would let a
    brand-new file pass vacuously until the moment it was staged.
    """
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [f for f in listing if f.endswith(SCAN_SUFFIXES) or os.path.basename(f) == "justfile"]


def main() -> int:
    report.enter_repo_root()

    failures = []
    for path in scanned_files():
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue

        here = os.path.dirname(path)
        for n, line in enumerate(lines, 1):
            for token in TOKEN.findall(line):
                # Globs and expansions are patterns, not references.
                if any(c in token for c in "*$[]"):
                    continue
                # Resolvable from the repo root OR from the directory of the
                # file that mentions it. The `source` lines at the top of every
                # script in tools/ are the second kind.
                #
                # Note this comment deliberately avoids writing an example path:
                # like the leak pattern, this gate would otherwise match itself.
                if os.path.exists(token) or os.path.exists(os.path.join(here, token)):
                    continue
                failures.append(f"{path}:{n} references '{token}', which does not exist")

    for failure in failures:
        report.fail(GATE, failure)
    if failures:
        return 1

    report.ok(GATE, "every repo path referenced in a comment resolves")
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
