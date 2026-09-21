#!/usr/bin/env python3
"""Verify GitHub Copilot's telemetry surface on this machine.

Run by `just copilot-smoke`.

The Claude Code side has had `just smoke` since v1; this side had nothing, and
the Copilot documentation carried a caution admitting every claim was derived
from vendor docs rather than observed. It no longer needs to: Copilot ships
built into VS Code, so its exporter is on disk. This costs no API calls, needs
no seat and needs no sign-in.

What it cannot do is generate traffic. Three claims need a signed-in session —
the CLI's http:// refusal, the billable-span regression on 1.130+, and content
exported despite captureContent=false. For the first of those, produce a dump
yourself and pass its path back.

This gate REPORTS; it does not fail on vendor behaviour. If the file-exporter
defect is fixed upstream that is a vendor improvement, and a check that turns
red on someone else's bug fix is a check nobody runs twice.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import copilot
import report

GATE = "copilot-smoke"

# Anchor on the exporter's own name, not on `createWriteStream`: that call
# appears throughout the bundle and only one of its sites is this exporter, so
# deleting the exporter outright would leave the anchor firing.
ANCHOR = re.compile(r"FileSpanExporter")

# Anchor on the catch, never on the function name: `safeStringify` in this
# bundle is Ajv's code generator, not this exporter.
HAZARD = re.compile(r'catch\s*\{?\s*\}?\s*\{?\s*return\s*"\{\}"')

PROXIMITY = 500

# Span → _spanProcessor → BatchSpanProcessor → _shutdownOnce → BindOnceFuture
# → _that → BatchSpanProcessor. That cycle is what JSON.stringify throws on.
CYCLE_SYMBOLS = ("_spanProcessor", "_shutdownOnce", "BindOnceFuture", r"this\._that")

# README trap 2 says the CLI silently refuses to export over http://, quoting
# `copilot help monitoring`: dropped "rather than sent in cleartext; startup is
# not aborted". If that behaviour is in a runtime, these words are in the file.
REFUSAL_FINGERPRINT = ("cleartext", "not aborted")

# The version copilot-cli#4567 was reported against. Anything older is outside
# the claim, and saying so is the difference between "disproved" and "untested".
REFUSAL_REPORTED_AGAINST = (1, 0, 80)

# Positive control. The refusal lives in the OTel code path, so a file with no
# OTel configuration in it is the wrong file and an absence there proves
# nothing at all.
CLI_OTEL_MARKER = "COPILOT_OTEL_ENABLED"

REMEDIATION = """
  Do not use otel.outfile for traces. Use
  github.copilot.chat.otel.dbSpanExporter.enabled TOGETHER WITH
  github.copilot.chat.otel.enabled — on its own it installs a span
  exporter that silently drops every batch.
"""


def banner(text: str) -> None:
    print(f"\n── {text} " + "─" * max(0, 68 - len(text)))


def host_version() -> str:
    """The VS Code version, or 'unknown'. Never allowed to abort the gate."""
    try:
        out = subprocess.run(
            ["code", "--version"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.splitlines()[0].strip() if out.strip() else "unknown"


def report_dump(path: Path) -> int:
    """Report the composition of a dump the exporter produced."""
    banner(f"dump: {path}")

    total = empty = blank = metrics = logs = other = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            total += 1
            if not line:
                blank += 1
            elif line == "{}":
                empty += 1
            elif '"scopeMetrics"' in line:
                metrics += 1
            elif '"hrTime"' in line:
                logs += 1
            else:
                other += 1

    print(f"  lines           {total}")
    print(f"  empty spans {{}} {empty}")
    print(f"  metric records  {metrics}")
    print(f"  log records     {logs}")
    print(f"  other           {other}")
    if blank:
        print(f"  blank           {blank}")

    # Positive control: refuse to report on a file that is not an OTel dump,
    # rather than call it clean. "No empty spans" is true of this source file.
    if not (empty or metrics or logs):
        report.die(
            GATE, f"{path} holds no recognisable OTel records — not a dump this gate can read"
        )

    print()
    if empty:
        # A record-counting inspector calls every one of those {} lines valid.
        print(f"  → {100 * empty / total:.1f}% of this file is empty spans\n")
        report.warn(GATE, "this dump contains empty spans — see README trap 8")
        report.ok(GATE, "dump inspected; its span records carry no data")
    else:
        report.ok(GATE, "dump inspected; no empty spans found")
    return 0


def inspect_bundle(ext_dir: Path) -> int:
    """Inspect the installed exporter without running anything."""
    manifest = ext_dir / copilot.MANIFEST
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, ValueError):
        version = "unknown"

    print(f"\ncopilot extension: {version}")
    print(f"vs code:           {host_version()}")
    print(f"bundle:            {ext_dir}")

    bundle = ext_dir / "dist" / "extension.js"
    banner("pass 1: the file exporter")
    if not bundle.is_file():
        report.note("bundle not found where expected")
        report.warn(GATE, "no exporter bundle where this gate expects it — nothing was proven")
        report.ok(GATE, "inconclusive: bundle layout is not one this gate understands")
        return 0

    source = bundle.read_text(encoding="utf-8", errors="replace")

    # Negative control FIRST. Everything below argues from a pattern being
    # present, so if the anchor itself is gone the bundle was restructured and
    # an absent hazard would read as a fixed hazard.
    anchors = [m.start() for m in ANCHOR.finditer(source)]
    if anchors:
        print(f"  ✓ anchor: FileSpanExporter ×{len(anchors)}")
    else:
        report.note("anchor: FileSpanExporter ×0")
        report.warn(
            GATE,
            "no file-exporter anchor in the bundle — an absent hazard here would prove nothing",
        )
        report.ok(GATE, "inconclusive: the exporter was restructured, re-derive the anchor")
        return 0

    near = [
        h.start()
        for h in HAZARD.finditer(source)
        if any(abs(h.start() - a) < PROXIMITY for a in anchors)
    ]
    if near:
        print(f'  ! serialiser: catch → "{{}}" inside the file exporter ×{len(near)}')
        print("    spans written by the file exporter will be the string {}")
    else:
        print('  ✓ serialiser: no catch → "{}" inside the file exporter')

    banner("pass 2: the circular reference")
    for symbol in CYCLE_SYMBOLS:
        count = len(re.findall(symbol, source))
        label = symbol.replace("\\", "")
        if count:
            print(f"  ✓ {label} ×{count}")
        else:
            report.note(f"{label} ×0")

    inspect_cli_runtime()

    print()
    if near:
        report.warn(GATE, "file exporter writes empty spans on this build — README trap 8")
        print(REMEDIATION)
        report.ok(GATE, "surface verified without a seat; the file exporter is unusable for traces")
    else:
        report.ok(
            GATE,
            "file exporter looks sound on this build — re-read README trap 8 before trusting it",
        )
    return 0


def inspect_cli_runtime() -> None:
    """Report what the installed CLI runtime does about README trap 2.

    Reports only. The refusal is vendor behaviour, and a check that turns red
    because someone else shipped a change is a check nobody runs twice.
    """
    banner("pass 3: the CLI runtime (README trap 2)")

    try:
        found = copilot.cli_runtime()
    except copilot.OverrideMissing as missing:
        report.die(GATE, str(missing))

    if found is None:
        report.note(f"no CLI runtime under {copilot.CLI_ROOT}")
        report.warn(GATE, "no Copilot CLI installed — trap 2 untested on this machine")
        return

    path, version = found
    print(f"  ✓ runtime: {version}")

    # Two shapes. The standalone unpack is one big app.js; the copy bundled
    # inside the extension puts its OTel logic in a native addon. Reading only
    # the first is how a review concluded the refusal did not exist anywhere.
    blobs = []
    for candidate in sorted(path.rglob("*")):
        if candidate.is_file() and candidate.suffix in (".js", ".node"):
            try:
                blobs.append(candidate.read_bytes())
            except OSError:
                continue
    source = b"\n".join(blobs).decode("utf-8", errors="replace")
    if not source:
        report.note("runtime holds no readable .js or .node")
        report.warn(GATE, "nothing to read in the runtime — cannot conclude")
        return

    # Negative control FIRST. Without it, a future layout that moves the OTel
    # code out of this file would read as "trap 2 disproved".
    if CLI_OTEL_MARKER not in source:
        report.note(f"{CLI_OTEL_MARKER} absent — this is not the OTel code path")
        report.warn(
            GATE,
            "the CLI runtime holds no OTel configuration — an absent refusal here proves nothing",
        )
        return

    print(f"  ✓ positive control: {CLI_OTEL_MARKER} present")

    present = [word for word in REFUSAL_FINGERPRINT if word in source]
    if present:
        print(f"  ! refusal fingerprint: {', '.join(present)}")
        # Scope matters more than presence. The refusal found in 1.0.73 is about
        # managed/enterprise headers, not about dropping export — reporting it
        # as "trap 2 holds" would restate the error this gate exists to correct.
        managed = "managed" in source.lower() and "headers" in source.lower()
        if managed:
            print("    scoped to MANAGED headers — credentials withheld, export proceeds")
            report.warn(
                GATE,
                f"CLI {version} refuses to attach managed headers to a cleartext "
                f"endpoint; it does NOT drop export — README trap 2",
            )
        else:
            report.warn(
                GATE,
                f"CLI {version} carries an unscoped cleartext refusal — re-read it, "
                f"this would be new behaviour",
            )
        return

    for word in REFUSAL_FINGERPRINT:
        report.note(f"'{word}' ×0")

    # The vendor's own worked example is the strongest counter-evidence there
    # is: it is the same help text trap 2 quotes against it.
    recommends_http = "OTEL_EXPORTER_OTLP_ENDPOINT=http://" in source
    if recommends_http:
        print("  ! help text recommends an http:// endpoint")

    older = copilot.version_key(version) < REFUSAL_REPORTED_AGAINST
    reported = ".".join(str(n) for n in REFUSAL_REPORTED_AGAINST)
    if older:
        report.warn(
            GATE,
            f"trap 2 not reproducible on CLI {version}, which predates the "
            f"{reported} it was reported against — untested, not disproved",
        )
    else:
        report.warn(
            GATE,
            f"trap 2 not reproducible on CLI {version}, at or past the {reported} "
            f"it was reported against — the claim needs re-sourcing",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="just copilot-smoke",
        description="Inspect the installed Copilot exporter, or report on a dump it produced.",
    )
    parser.add_argument(
        "dump",
        nargs="?",
        default="",
        help="an OTel dump the file exporter produced; omit to inspect the installed build",
    )
    # `just` always passes the parameter, so an empty string means "not
    # supplied" and must not be mistaken for a path.
    args = parser.parse_args()

    report.enter_repo_root()

    if args.dump:
        path = Path(args.dump)
        if not path.is_file():
            report.die(GATE, f"{path} does not exist")
        return report_dump(path)

    try:
        ext_dir = copilot.ext_dir()
    except copilot.OverrideMissing as missing:
        report.die(GATE, str(missing))

    if ext_dir is None:
        report.warn(GATE, "no VS Code Copilot build found — set COPILOT_EXT_DIR to inspect one")
        report.ok(GATE, "skipped: nothing installed to inspect")
        return 0

    return inspect_bundle(ext_dir)


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
