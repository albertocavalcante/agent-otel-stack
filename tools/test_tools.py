#!/usr/bin/env python3
"""Self-tests for the gates. Run by `just test`.

These exist because the tooling was, for a while, the least-verified code in a
repository whose entire thesis is that unverified things fail silently. Every
case below is one that was actually run by hand during development and then
lost when the session ended — the drills were real, they just did not survive.

Deliberately dependency-free: no pytest, no fixtures directory, no conftest.
A test file that needs installing is a test file that stops being run.

Each case names the defect it would have caught. If a case ever looks
redundant, check the git history before deleting it — several of these are here
because the obvious implementation was wrong twice.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "lib"))

import copilot  # noqa: E402
import trap_check  # noqa: E402

FAILURES: list[str] = []


def check(name: str, got, want) -> None:
    if got == want:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}\n      got  {got!r}\n      want {want!r}")
        FAILURES.append(name)


# --------------------------------------------------------------------------
# trap_check.anchor_for — reimplements GitHub's heading-slug algorithm.
# Wrong twice: once collapsing whitespace runs, once dropping underscores.
# --------------------------------------------------------------------------
def test_anchor_for() -> None:
    print("trap_check.anchor_for")
    cases = [
        ("1. No default protocol", "1-no-default-protocol"),
        # backticks vanish, `://` vanishes, the double space left by removing
        # it survives as two hyphens
        (
            "2. The CLI refuses `http://` — for enterprise headers, not for export",
            "2-the-cli-refuses-http--for-enterprise-headers-not-for-export",
        ),
        # underscores are word characters and MUST survive
        ("6. `nano_aiu` is duplicated onto children", "6-nano_aiu-is-duplicated-onto-children"),
        # GitHub replaces each space individually; collapsing runs is the bug
        ("12. Some  Trap", "12-some--trap"),
        ("3. delta versus cumulative", "3-delta-versus-cumulative"),
    ]
    for heading, want in cases:
        check(f"  {heading[:44]}", trap_check.anchor_for(heading), want)


# --------------------------------------------------------------------------
# copilot.version_key — 1.0.54 must outrank 0.0.396. Naive string sort does
# not, and that is how the newest CLI runtime went unnoticed.
# --------------------------------------------------------------------------
def test_version_key() -> None:
    print("copilot.version_key")
    check("1.0.54 > 0.0.396", copilot.version_key("1.0.54") > copilot.version_key("0.0.396"), True)
    check("1.0.73 > 1.0.54", copilot.version_key("1.0.73") > copilot.version_key("1.0.54"), True)
    check("non-numeric is lowest", copilot.version_key("latest"), (0,))


# --------------------------------------------------------------------------
# copilot.expected_spans_columns — the DDL parser. Truncated at the first ")"
# until a nested DEFAULT (strftime(...)) proved it, and then broke the other
# way by splitting per line when the real DDL packs several columns per line.
# --------------------------------------------------------------------------
def test_expected_spans_columns() -> None:
    print("copilot.expected_spans_columns")
    with tempfile.TemporaryDirectory() as tmp:
        ext = Path(tmp)
        (ext / "dist").mkdir()

        (ext / "dist" / "extension.js").write_text(
            "x=1;e.exec(`CREATE TABLE IF NOT EXISTS spans ("
            "span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,"
            "created_at TEXT DEFAULT (strftime('%s','now')),"
            "end_time_ms INTEGER, input_tokens INTEGER);`)"
        )
        got = copilot.expected_spans_columns(ext)
        check(
            "survives a nested computed default",
            got,
            {"span_id", "trace_id", "created_at", "end_time_ms", "input_tokens"},
        )

        (ext / "dist" / "extension.js").write_text("no ddl here at all")
        check("no DDL -> None, not empty set", copilot.expected_spans_columns(ext), None)


# --------------------------------------------------------------------------
# lint.sh's embedded-language gate. Nine bypass shapes, three allowed forms.
# The first version matched `python3 --version` and missed `PY=python3`.
# --------------------------------------------------------------------------
def test_interpreter_gate() -> None:
    print("lint.sh embedded-interpreter gate")
    caught = [
        ('python3 -c "print(1)"', "inline -c"),
        ('PY=python3\n$PY -c "print(1)"', "variable indirection"),
        ("python3 <<EOF\nprint(1)\nEOF", "heredoc, no flag"),
        ('python3 <<< "print(1)"', "herestring"),
        ("echo x | python3", "pipe"),
        ('env python3 -c "print(1)"', "env prefix"),
        ('/usr/bin/python3 -c "print(1)"', "absolute path"),
        ('node -e "1"', "node"),
        ('perl -e "1"', "perl"),
    ]
    allowed = [
        ("command -v python3 >/dev/null", "command -v"),
        ("require_cmd python3", "require_cmd"),
        ("# we used to call python3 here", "comment"),
    ]
    root = TOOLS.parent
    probe = TOOLS / "_probe_test.sh"
    original = (TOOLS / "stack.sh").read_text()
    try:
        for body, label in caught + allowed:
            probe.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body + "\n")
            rc = subprocess.run(
                [str(TOOLS / "lint.sh")], cwd=root, capture_output=True, text=True
            ).returncode
            want_fail = (body, label) in caught
            check(f"  {label}", rc != 0, want_fail)
    finally:
        probe.unlink(missing_ok=True)
        (TOOLS / "stack.sh").write_text(original)


# --------------------------------------------------------------------------
# otel_check.check_durability — the settings whose defaults destroy data.
# --------------------------------------------------------------------------
def test_check_durability() -> None:
    print("otel_check.check_durability")
    import otel_check

    def config(**over):
        queue = {
            "enabled": True,
            "storage": "file_storage/queue",
            "block_on_overflow": True,
        }
        retry = {"enabled": True, "max_elapsed_time": 0}
        queue.update(over.pop("queue", {}))
        retry.update(over.pop("retry", {}))
        return {
            "extensions": {"file_storage/queue": {}},
            "exporters": {"otlp_http/gateway": {"sending_queue": queue, "retry_on_failure": retry}},
            "service": {"extensions": ["file_storage/queue"]},
        }

    check("a sound config has no findings", otel_check.check_durability(config()), [])

    cases = [
        ({"retry": {"max_elapsed_time": "300s"}}, "max_elapsed_time"),
        ({"queue": {"block_on_overflow": False}}, "block_on_overflow"),
        ({"queue": {"storage": None}}, "no `storage`"),
        ({"queue": {"storage": "file_storage/absent"}}, "not a defined"),
    ]
    for over, fragment in cases:
        found = otel_check.check_durability(config(**over))
        check(f"  catches {fragment}", any(fragment in e for e in found), True)

    no_storage = config()
    no_storage["extensions"] = {}
    no_storage["service"]["extensions"] = []
    check(
        "  catches a missing file_storage extension",
        any("no `file_storage`" in e for e in otel_check.check_durability(no_storage)),
        True,
    )


# --------------------------------------------------------------------------
# dash-check.sh — the Grafana export artefacts that silently fail to bind.
# --------------------------------------------------------------------------
def test_dash_check() -> None:
    print("dash-check.sh")
    root = TOOLS.parent
    target = root / "dashboards" / "_probe_test.json"
    sound = {
        "uid": "probe",
        "title": "probe",
        "panels": [
            {
                "datasource": {"type": "prometheus", "uid": "agent-otel-prom"},
                "targets": [{"datasource": {"type": "prometheus", "uid": "agent-otel-prom"}}],
            }
        ],
    }

    def run(doc) -> int:
        target.write_text(json.dumps(doc))
        return subprocess.run(
            [str(TOOLS / "dash-check.sh")], cwd=root, capture_output=True, text=True
        ).returncode

    try:
        check("  a sound dashboard passes", run(sound) == 0, True)

        unprovisioned = json.loads(json.dumps(sound).replace("agent-otel-prom", "nope"))
        check("  catches an unprovisioned uid", run(unprovisioned) != 0, True)

        placeholder = json.loads(json.dumps(sound).replace("agent-otel-prom", "${DS_PROMETHEUS}"))
        check("  catches a ${DS_} placeholder", run(placeholder) != 0, True)

        with_inputs = dict(sound, __inputs=[{"name": "DS_PROMETHEUS"}])
        check("  catches __inputs", run(with_inputs) != 0, True)
    finally:
        target.unlink(missing_ok=True)


def main() -> int:
    for test in (
        test_anchor_for,
        test_version_key,
        test_expected_spans_columns,
        test_interpreter_gate,
        test_check_durability,
        test_dash_check,
    ):
        test()

    print()
    if FAILURES:
        print(f"✗ test: {len(FAILURES)} failed — {', '.join(FAILURES)}", file=sys.stderr)
        return 1
    print("✓ test: every tool self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
