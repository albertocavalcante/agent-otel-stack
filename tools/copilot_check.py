#!/usr/bin/env python3
"""Fail if a documented Copilot setting has drifted from the installed build.

Run by `just copilot-check`.

Every other gate in this repo checks structure: links resolve, paths exist, YAML
binds to a datasource. None of them checks whether a documented CLAIM is true,
and on 2026-09-21 three were not. The settings table listed five of eleven keys.
The headers setting was documented as not existing. An agent-host namespace was
marked unconfirmed. All three were readable on disk the whole time, because
Copilot ships built into VS Code rather than as a marketplace extension — so a
gate can simply look.

Not finding VS Code is not a failure. On a machine without it this warns and
passes, the same way pass 3 of the smoke gate refuses to conclude from a missing
positive control.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import copilot
import report

GATE = "copilot-check"
PREFIX = "github.copilot.chat.otel."
DOC = "docs/02-copilot.md"
ENV = "otel/env/copilot-vscode.env"
TABLE_ANCHOR = "All eleven keys, prefix"

# The doc table abbreviates types; the manifest uses JSON Schema names.
TYPE_ALIASES = {"bool": "boolean", "int": "integer"}

NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen",
}  # fmt: skip


def literal(raw: str):
    """Parse a documented table cell into the value the manifest would hold."""
    raw = raw.strip().strip("`").strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def same(a, b) -> bool:
    """Compare by serialisation, not by ==.

    Python holds 0 == False == 0.0, so a documented default of 0 would match a
    build that actually ships false. For maxAttributeSizeChars that is the
    difference between "truncation disabled" and a boolean.
    """
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def real_settings(manifest: Path) -> tuple[dict, str]:
    """Every PREFIX key the installed build declares, plus its version."""
    with manifest.open(encoding="utf-8") as handle:
        doc = json.load(handle)

    blocks = doc.get("contributes", {}).get("configuration") or []
    if isinstance(blocks, dict):
        blocks = [blocks]

    real = {}
    for block in blocks:
        for key, spec in (block or {}).get("properties", {}).items():
            if key.startswith(PREFIX):
                real[key[len(PREFIX) :]] = spec

    return real, doc.get("version", "unknown")


def documented_settings() -> tuple[dict, str | None]:
    """The doc table's keys mapped to (type, default), plus its anchor line.

    The table is the only place carrying documented DEFAULTS. The env file
    carries an example configuration, whose values are deliberately not
    defaults.
    """
    lines = Path(DOC).read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if TABLE_ANCHOR in line), None)
    if start is None:
        return {}, None

    documented = {}
    for line in lines[start:]:
        if not line.startswith("|"):
            if documented:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0].startswith("`"):
            continue
        documented[cells[0].strip("`")] = (cells[1], cells[2])

    return documented, lines[start]


def configured_settings() -> set[str]:
    """Keys appearing in the env file's settings.json snippet."""
    pattern = re.compile(r'"' + re.escape(PREFIX) + r'([A-Za-z.]+)"\s*:')
    text = Path(ENV).read_text(encoding="utf-8")
    return set(pattern.findall(text))


def compare(real: dict, version: str, documented: dict, anchor: str | None,
            env_keys: set[str]) -> list[str]:  # fmt: skip
    errors = []

    if anchor is None:
        errors.append(
            f"{DOC} no longer contains the settings table anchored on "
            f"'{TABLE_ANCHOR}' — this gate cannot find what to check"
        )

    for key in sorted(set(documented) - set(real)):
        errors.append(
            f"{DOC} documents '{PREFIX}{key}', which the installed {version} build does not define"
        )

    for key in sorted(set(real) - set(documented)):
        errors.append(
            f"the installed {version} build defines '{PREFIX}{key}', which {DOC} does not document"
        )

    for key in sorted(set(real) - env_keys):
        errors.append(
            f"the installed {version} build defines '{PREFIX}{key}', "
            f"which is missing from the settings snippet in {ENV}"
        )

    # Both directions. A key withdrawn upstream but left in the snippet is
    # exactly the stale claim this gate exists to catch.
    for key in sorted(env_keys - set(real)):
        errors.append(
            f"{ENV} configures '{PREFIX}{key}', which the installed {version} build does not define"
        )

    for key in sorted(set(documented) & set(real)):
        doc_type, doc_default = documented[key]
        spec = real[key]
        want_type = TYPE_ALIASES.get(doc_type, doc_type)
        if want_type != spec.get("type"):
            errors.append(
                f"'{PREFIX}{key}' is documented as type {doc_type} but the "
                f"installed build declares {spec.get('type')}"
            )
        if not same(literal(doc_default), spec.get("default")):
            errors.append(
                f"'{PREFIX}{key}' is documented with default {doc_default} "
                f"but the installed build defaults to {json.dumps(spec.get('default'))}"
            )

    # The prose count is part of the claim. A twelfth key plus an updated table
    # would otherwise leave "All eleven keys" false and this gate green.
    expected = NUMBER_WORDS.get(len(real))
    if anchor is not None and expected and expected not in anchor.lower():
        errors.append(
            f"{DOC} says '{anchor.strip()}' but the installed {version} build "
            f"defines {len(real)} keys ({expected})"
        )

    return errors


def main() -> int:
    report.enter_repo_root()

    try:
        ext_dir = copilot.ext_dir()
    except copilot.OverrideMissing as missing:
        report.die(GATE, str(missing))

    if ext_dir is None:
        report.warn(
            GATE, "no VS Code Copilot build found — set COPILOT_EXT_DIR to check against one"
        )
        report.ok(GATE, "skipped: nothing installed to compare the docs against")
        return 0

    real, version = real_settings(ext_dir / copilot.MANIFEST)

    # Negative control. An empty set means the bundle layout moved, and every
    # assertion below would then pass against nothing at all.
    if not real:
        report.warn(GATE, f"{ext_dir} exposes no OTel settings — cannot conclude")
        report.ok(GATE, "skipped: the installed build's layout is not one this gate understands")
        return 0

    documented, anchor = documented_settings()
    errors = compare(real, version, documented, anchor, configured_settings())

    for error in errors:
        report.fail(GATE, error)
    if errors:
        return 1

    report.ok(
        GATE,
        f"{len(real)} documented settings match the installed build (copilot-chat {version})",
    )
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
