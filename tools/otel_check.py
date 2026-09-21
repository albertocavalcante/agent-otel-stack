#!/usr/bin/env python3
"""Structurally validate the collector config without the collector.

Run by `just otel-check`.

`otelcol validate` needs the binary. These are checkable from the YAML alone: a
pipeline naming an undefined component (whose startup error reads like "my
endpoint is wrong"), memory_limiter not first, batch not last.

This used a hand-rolled indentation reader until a review found four false
PASSes on legal YAML — block sequences, inline comments, multi-line flow
sequences and anchors all slipped through *silently*, and a pipeline named with
a dash was invisible to it. A gate that under-checks without saying so is worse
than no gate. It uses a real parser now.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import report

GATE = "otel-check"

# The agent runs on a laptop and must survive it; the gateway runs beside the
# backends and does not carry a queue. Only the agent is held to the durability
# rules below.
AGENT = "otel/collector-agent.yaml"
GATEWAY = "otel/collector-gateway.yaml"
CONFIGS = (AGENT, GATEWAY)


def names(doc: dict, section: str) -> set[str]:
    block = doc.get(section) or {}
    return set(block) if isinstance(block, dict) else set()


def body(doc: dict, section: str, name: str) -> dict:
    """A single component's own config, empty when absent or not a mapping."""
    block = doc.get(section) or {}
    if not isinstance(block, dict):
        return {}
    spec = block.get(name) or {}
    return spec if isinstance(spec, dict) else {}


def check_durability(doc: dict) -> list[str]:
    """Assert the agent can lose its network and its process without losing data.

    Every one of these defaults is silent. A collector with none of them set
    starts, runs, reports success, and drops everything in flight the moment it
    restarts — which is the failure this repository exists to document.
    """
    errors: list[str] = []

    storages = {n for n in names(doc, "extensions") if n.split("/")[0] == "file_storage"}
    if not storages:
        errors.append(
            "no `file_storage` extension — the sending queue would be memory-only, "
            "so a restart silently discards whatever is in flight"
        )

    declared = {str(x) for x in (doc.get("service") or {}).get("extensions") or []}
    for storage in sorted(storages - declared):
        errors.append(
            f"`{storage}` is defined but missing from `service.extensions` — "
            f"an extension the service does not list never starts"
        )

    for name in sorted(names(doc, "exporters")):
        spec = body(doc, "exporters", name)

        queue = spec.get("sending_queue")
        if not isinstance(queue, dict) or queue.get("enabled") is not True:
            errors.append(
                f"exporter `{name}` enables no `sending_queue` — a collector restart "
                f"silently discards whatever is in flight"
            )
        else:
            if not queue.get("storage"):
                errors.append(
                    f"exporter `{name}`.sending_queue sets no `storage` — the queue is "
                    f"memory-only and does not survive a restart"
                )
            if queue.get("block_on_overflow") is not True:
                errors.append(
                    f"exporter `{name}`.sending_queue does not set "
                    f"`block_on_overflow: true` — the default DROPS when the queue fills"
                )

        retry = spec.get("retry_on_failure")
        if not isinstance(retry, dict) or retry.get("enabled") is not True:
            errors.append(f"exporter `{name}` enables no `retry_on_failure`")
        elif retry.get("max_elapsed_time") not in (0, "0", "0s"):
            errors.append(
                f"exporter `{name}`.retry_on_failure sets "
                f"`max_elapsed_time: {retry.get('max_elapsed_time')}` — on expiry the "
                f"item is DELETED from disk, so a long offline period destroys a "
                f"backlog that was already safely persisted. Use 0"
            )

    return errors


def check(doc: dict) -> list[str]:
    errors: list[str] = []

    # Connectors are simultaneously exporters and receivers by design; omitting
    # them made the standard spanmetrics pattern report a phantom undefined
    # exporter.
    connectors = names(doc, "connectors")
    defined = {
        "receivers": names(doc, "receivers") | connectors,
        "processors": names(doc, "processors"),
        "exporters": names(doc, "exporters") | connectors,
        "extensions": names(doc, "extensions"),
    }

    service = doc.get("service")
    if not isinstance(service, dict):
        errors.append("no `service:` block — the collector has nothing to run")
        return errors

    pipelines = service.get("pipelines") or {}
    if not isinstance(pipelines, dict) or not pipelines:
        errors.append("`service.pipelines` is empty — nothing would flow")

    for name, spec in pipelines.items() if isinstance(pipelines, dict) else []:
        if not isinstance(spec, dict):
            errors.append(f"pipeline `{name}` is not a mapping")
            continue

        for kind in ("receivers", "processors", "exporters"):
            used = spec.get(kind)
            if used is None:
                if kind != "processors":
                    errors.append(f"pipeline `{name}` declares no {kind}")
                continue
            if not isinstance(used, list):
                errors.append(f"pipeline `{name}`.{kind} is not a list")
                continue

            used = [str(x) for x in used]
            for comp in used:
                if comp not in defined[kind]:
                    errors.append(
                        f"pipeline `{name}` uses {kind[:-1]} `{comp}`, "
                        f"which is not defined under `{kind}:`"
                    )

            if kind == "processors" and used:
                if used[0] != "memory_limiter":
                    errors.append(
                        f"pipeline `{name}`: memory_limiter must be FIRST "
                        f"(found `{used[0]}`) or the collector can OOM before it applies"
                    )
                if "batch" in used and used[-1] != "batch":
                    errors.append(f"pipeline `{name}`: batch must be LAST (found `{used[-1]}`)")

    for comp in service.get("extensions") or []:
        if str(comp) not in defined["extensions"]:
            errors.append(f"service.extensions uses `{comp}`, which is not defined")

    return errors


def load(yaml, path: str) -> dict:
    config = Path(path)
    if not config.is_file():
        report.die(GATE, f"{path} is missing — a deleted config must fail, not pass")

    try:
        with config.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        report.die(GATE, f"{path} is not valid YAML: {exc}")


def main() -> int:
    report.enter_repo_root()

    try:
        import yaml
    except ImportError:
        report.die(GATE, "PyYAML not available (pip install pyyaml, or brew install yq)")

    errors: list[str] = []
    for path in CONFIGS:
        doc = load(yaml, path)
        found = check(doc)
        if path == AGENT:
            found += check_durability(doc)
        errors += [f"{path}: {e}" for e in found]

    for error in errors:
        report.fail(GATE, error)
    if errors:
        return 1

    report.ok(GATE, f"{len(CONFIGS)} collector configs are structurally valid and durable")
    return 0


if __name__ == "__main__":
    sys.exit(report.guard(GATE, main))
