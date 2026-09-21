#!/usr/bin/env python3
"""Report what is actually in Copilot's local SQLite span store.

Run by `just copilot-traces`.

`otel.dbSpanExporter.enabled` writes spans to `agent-traces.db`, and that store
is the only durable local copy of a span when the collector was not running. A
replay tool is the obvious next thing to build — but a parser tested only
against a fixture of one's own construction proves that the fixture and the
parser agree, not that either matches what the vendor writes. This reads the
real thing, so the replay can be designed against a schema confirmed in the
wild.

It is also the honest counterweight to calling SQLite "the durable copy". The
store is LOSSY relative to OTLP: millisecond timestamps where OTLP is
nanoseconds, no resource, no instrumentation scope, and every attribute value
stringified. A replay reconstructs spans; it does not restore them.

This gate never writes. The database belongs to a running editor.
"""

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import copilot
import report

GATE = "copilot-traces"

# Columns worth reporting on individually: a column that exists but is entirely
# NULL is the difference between "we can compute cache-hit rate from this" and
# "we cannot", and `PRAGMA table_info` cannot tell them apart.
SIGNAL_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "ttft_ms",
    "request_model",
    "response_model",
    "conversation_id",
    "parent_span_id",
)

ENABLE_HINT = """    Both settings are required:
      "github.copilot.chat.otel.enabled": true,
      "github.copilot.chat.otel.dbSpanExporter.enabled": true
    dbSpanExporter alone installs a null span exporter — README trap 8."""


def connect(path: Path) -> tuple[sqlite3.Connection, bool] | None:
    """Open read-only, preferring a live read but never needing write access.

    `mode=ro` sees data still sitting in the write-ahead log, but needs to map
    the -shm file and yields to a writer's lock. `immutable=1` needs neither
    and cannot touch the database, at the cost of not seeing unflushed WAL
    content. Try the accurate one, fall back to the safe one, and say which.

    Opening is not enough to know either works: SQLite defers the real check to
    the first query, so each mode is probed with one.
    """
    for uri, immutable in (
        (f"file:{path}?mode=ro", False),
        (f"file:{path}?mode=ro&immutable=1", True),
    ):
        try:
            db = sqlite3.connect(uri, uri=True, timeout=2)
            db.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return db, immutable
        except sqlite3.Error:
            continue

    return None


def table_columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]


def as_date(ms: int | None) -> str:
    if not ms:
        return "unknown"
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")


def describe(db: sqlite3.Connection, path: Path, immutable: bool) -> None:
    columns = table_columns(db, "spans")

    # Negative control FIRST. A file without a spans table is not this store,
    # and reporting "0 spans" for it reads as "you have no telemetry".
    if not columns:
        report.note("no `spans` table")
        report.warn(GATE, f"{path} has no spans table — this is not the store this gate reads")
        report.ok(GATE, "inconclusive: not a Copilot span store")
        return

    try:
        version = db.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        version = version[0] if version else None
    except sqlite3.Error:
        version = None

    count = db.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
    print(f"  ✓ schema_version  {version if version is not None else 'absent'}")
    print(f"  ✓ spans           {count}")
    if immutable:
        report.note("opened immutable — spans still in the WAL are not counted")

    if not count:
        print()
        report.warn(GATE, "the store exists but holds no spans — nothing to replay yet")
        report.ok(GATE, f"store present at schema {version}, empty")
        return

    lo, hi = db.execute("SELECT MIN(start_time_ms), MAX(end_time_ms) FROM spans").fetchone()
    print(f"  ✓ oldest          {as_date(lo)}")
    print(f"  ✓ newest          {as_date(hi)}")

    operations = db.execute(
        "SELECT operation_name, COUNT(*) FROM spans GROUP BY operation_name ORDER BY 2 DESC"
    ).fetchall()
    print("  ✓ operations      " + ", ".join(f"{name or 'null'}×{n}" for name, n in operations))

    # Present-but-empty is the finding. A NULL cached_tokens column means the
    # cache-hit rate this repo exists to compute is not in this store.
    print("\n  populated columns:")
    for column in SIGNAL_COLUMNS:
        if column not in columns:
            report.note(f"{column} — column absent")
            continue
        filled = db.execute(f"SELECT COUNT({column}) FROM spans").fetchone()[0]
        if filled:
            print(f"  ✓ {column} {filled}/{count}")
        else:
            report.note(f"{column} — present but entirely NULL")

    attributes = db.execute("SELECT COUNT(*) FROM span_attributes").fetchone()[0]
    events = db.execute("SELECT COUNT(*) FROM span_events").fetchone()[0]
    print(f"\n  ✓ span_attributes {attributes}")
    print(f"  ✓ span_events     {events}")

    print()
    report.ok(GATE, f"{count} spans at schema {version}, {as_date(lo)} to {as_date(hi)}")


def check_drift(db: sqlite3.Connection) -> None:
    """Compare the store's columns against the DDL the installed bundle writes.

    The vendor's own DDL is the expected value. A store that no longer matches
    the product that writes it is the signal a replay tool would need.
    """
    try:
        ext = copilot.ext_dir()
    except copilot.OverrideMissing:
        ext = None
    if ext is None:
        report.note("no VS Code build to compare the schema against")
        return

    expected = copilot.expected_spans_columns(ext)
    if expected is None:
        report.note("no spans DDL in the installed bundle — cannot compare")
        return

    actual = set(table_columns(db, "spans"))
    if not actual:
        return

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if not missing and not extra:
        print(f"  ✓ schema matches the installed bundle ({len(expected)} columns)")
        return

    for column in missing:
        report.warn(GATE, f"bundle declares `{column}`, the store does not have it")
    for column in extra:
        report.warn(GATE, f"the store has `{column}`, the installed bundle does not declare it")


def main() -> int:
    report.enter_repo_root()

    try:
        path = copilot.traces_db()
    except copilot.OverrideMissing as missing:
        report.die(GATE, str(missing))

    print(f"\n── {copilot.TRACES_DB} " + "─" * 48)

    if path is None:
        report.note(f"not found — {copilot.TRACES_DB} has never been written")
        print(ENABLE_HINT)
        print()
        report.warn(GATE, "no local span store — dbSpanExporter has not run on this machine")
        report.ok(GATE, "skipped: nothing to inspect until the store exists")
        return 0

    print(f"  ✓ path            {path}")
    print(f"  ✓ size            {path.stat().st_size:,} bytes")

    opened = connect(path)
    if opened is None:
        # A writer holding the database is a state, not a fault. Saying so is
        # the difference between "try again" and "this gate is broken".
        report.note("could not read — another process holds it locked")
        report.warn(GATE, f"{path} is locked by a writer; close VS Code or retry")
        report.ok(GATE, "inconclusive: the store was busy")
        return 0

    db, immutable = opened
    try:
        check_drift(db)
        describe(db, path, immutable)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
