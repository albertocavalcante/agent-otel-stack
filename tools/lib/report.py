"""Shared reporting for the repository's Python gates — the twin of common.sh.

Import this, don't run it:

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import report

The glyphs and streams below must match common.sh byte for byte. Shell gates and
Python gates write to the same terminal in the same `just check` run, and a
reader should not be able to tell which language produced a line.

    ok    "✓ name: msg"  stdout  no exit
    warn  "! name: msg"  stderr  no exit
    fail  "✗ name: msg"  stderr  no exit
    die   "✗ name: msg"  stderr  exit 1
    note  "  · msg"      stdout  no exit
"""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn


def repo_root() -> Path:
    """Absolute repository root, resolved from this file rather than the cwd.

    Deliberately not `git rev-parse`: common.sh resolves the same way, and a
    gate must behave identically whether or not it is run inside a work tree.
    """
    return Path(__file__).resolve().parents[2]


def enter_repo_root() -> Path:
    """chdir to the repository root, mirroring `cd "$(repo_root)"` in every gate.

    Gates open repo-relative paths and shell out to `git ls-files`, both of
    which resolve against the cwd.
    """
    root = repo_root()
    os.chdir(root)
    return root


def ok(name: str, msg: str) -> None:
    print(f"✓ {name}: {msg}")


def _to_stderr(glyph: str, name: str, msg: str) -> None:
    """Write a diagnostic, keeping it in order with the report it refers to.

    Python line-buffers stdout to a terminal but block-buffers it to a pipe,
    while stderr is unbuffered. Without this flush a gate's ✗ line overtakes the
    output it is explaining the moment anyone runs `just check | tee`.
    """
    sys.stdout.flush()
    print(f"{glyph} {name}: {msg}", file=sys.stderr, flush=True)


def warn(name: str, msg: str) -> None:
    """Completed but inconclusive is not failure, and must not look like success."""
    _to_stderr("!", name, msg)


def fail(name: str, msg: str) -> None:
    _to_stderr("✗", name, msg)


def die(name: str, msg: str) -> NoReturn:
    fail(name, msg)
    sys.exit(1)


def note(msg: str) -> None:
    """A sub-result that was not observed. Distinct from both success and failure."""
    print(f"  · {msg}")


def guard(name: str, main: Callable[[], int]) -> int:
    """Run a gate's main(), reporting an unhandled exception as a gate FAULT.

    Without this a JSONDecodeError on an input file exits 1, which every caller
    reads as "the thing this gate checks is wrong" — sending the reader to edit
    documentation that was never the problem.
    """
    try:
        return main()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        fail(name, f"{type(exc).__name__}: {exc}")
        die(name, "this is a fault in the gate or its inputs, not a finding")
