#!/usr/bin/env python3
"""Post one span to the agent and prove it reaches Tempo.

Run by `just stack-check`.

This is the only assertion in the repository that exercises the whole path. A
stack that starts is not a stack that works: every service can report healthy
while a span posted at one end never arrives at the other, because the failures
this repository documents are all silent.

It lives in Python rather than inside `tools/stack.sh` because it is JSON
construction and JSON parsing, and because the one thing this repository will
not do is embed one language inside another — see `just lint`, which now fails
on exactly that.

Two details that already cost a debugging session:

- Tempo returns span and trace IDs **base64-encoded**, not as the hex you sent.
  Grepping for the hex never matches, and the check then reports "the span
  never arrived" for a span sitting in the database.
- The agent batches for 5s, the gateway for another 5s, and Tempo has to flush
  before a trace is queryable. A probe that gives up in under ~20s reports a
  working pipeline as broken.
"""

import argparse
import base64
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import report

GATE = "stack-check"

AGENT_TRACES = "http://127.0.0.1:4318/v1/traces"
TEMPO_TRACE = "http://127.0.0.1:3200/api/traces/{trace_id}"

SERVICE_NAME = "agent-otel-stack-check"


def build_span(trace_id: str, span_id: str) -> bytes:
    """One OTLP/JSON span, shaped like something this repo would actually see."""
    now = time.time_ns()
    return json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": SERVICE_NAME}}
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "just-stack-check"},
                            "spans": [
                                {
                                    "traceId": trace_id,
                                    "spanId": span_id,
                                    "name": "stack-check",
                                    "kind": 1,
                                    "startTimeUnixNano": str(now),
                                    "endTimeUnixNano": str(now + 1_000_000),
                                    "attributes": [
                                        {
                                            "key": "gen_ai.operation.name",
                                            "value": {"stringValue": "chat"},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    ).encode()


def post(url: str, payload: bytes, timeout: int = 10) -> int:
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.status


def contains_span(document: dict, span_id: str) -> bool:
    """Tempo encodes IDs base64; decode rather than compare the wrong shape."""
    for batch in document.get("batches", []):
        for scope in batch.get("scopeSpans", []):
            for span in scope.get("spans", []):
                raw = span.get("spanId", "")
                try:
                    if base64.b64decode(raw).hex() == span_id:
                        return True
                except (ValueError, TypeError):
                    continue
    return False


def await_trace(trace_id: str, span_id: str, budget: int) -> bool:
    url = TEMPO_TRACE.format(trace_id=trace_id)
    waited = 0
    while waited < budget:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
                if contains_span(json.load(response), span_id):
                    return True
        except (urllib.error.URLError, ValueError, TimeoutError):
            pass
        time.sleep(3)
        waited += 3
    return False


def main() -> int:
    parser = argparse.ArgumentParser(prog="just stack-check")
    parser.add_argument(
        "--timeout", type=int, default=90, help="seconds to wait for the span to reach Tempo"
    )
    args = parser.parse_args()

    report.enter_repo_root()

    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)

    print("\n── posting one span to the agent ──────────────────────────────────────")
    print(f"  trace_id {trace_id}")

    try:
        post(AGENT_TRACES, build_span(trace_id, span_id))
    except (urllib.error.URLError, TimeoutError) as exc:
        report.die(GATE, f"the agent refused the span ({exc}) — is the stack up?")
    report.ok(GATE, "agent accepted it")

    print("\n── asking tempo for it ────────────────────────────────────────────────")
    if await_trace(trace_id, span_id, args.timeout):
        print()
        report.ok(GATE, "span made the full trip: agent → gateway → tempo")
        return 0

    print()
    report.fail(GATE, f"the span never reached tempo after {args.timeout}s")
    report.warn(GATE, "check the gateway: `just logs collector-gateway`")
    return 1


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
