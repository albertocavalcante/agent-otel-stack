#!/usr/bin/env bash
# tools/otel-check.sh — structurally validate the collector config without the
# collector. Run by `just otel-check`.
#
# `otelcol validate` needs the binary. These are checkable from the YAML alone:
# a pipeline naming an undefined component (whose startup error reads like "my
# endpoint is wrong"), memory_limiter not first, batch not last.
#
# This used a hand-rolled indentation reader until a review found four false
# PASSes on legal YAML — block sequences, inline comments, multi-line flow
# sequences and anchors all slipped through *silently*, and a pipeline named
# with a dash was invisible to it. A gate that under-checks without saying so is
# worse than no gate. It uses a real parser now.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

CONFIG="otel/collector.yaml"
if [ ! -f "$CONFIG" ]; then
  die otel-check "$CONFIG is missing — a deleted config must fail, not pass"
fi

require_cmd python3

python3 - "$CONFIG" <<'PY'
import sys

try:
    import yaml
except ImportError:
    print("✗ otel-check: PyYAML not available (pip install pyyaml, or brew install yq)",
          file=sys.stderr)
    sys.exit(1)

path = sys.argv[1]
try:
    doc = yaml.safe_load(open(path)) or {}
except yaml.YAMLError as exc:
    print(f"✗ otel-check: {path} is not valid YAML: {exc}", file=sys.stderr)
    sys.exit(1)

errors = []

def names(section):
    block = doc.get(section) or {}
    return set(block) if isinstance(block, dict) else set()

# Connectors are simultaneously exporters and receivers by design; omitting them
# made the standard spanmetrics pattern report a phantom undefined exporter.
connectors = names("connectors")
defined = {
    "receivers": names("receivers") | connectors,
    "processors": names("processors"),
    "exporters": names("exporters") | connectors,
    "extensions": names("extensions"),
}

service = doc.get("service")
if not isinstance(service, dict):
    errors.append("no `service:` block — the collector has nothing to run")
else:
    pipelines = service.get("pipelines") or {}
    if not isinstance(pipelines, dict) or not pipelines:
        errors.append("`service.pipelines` is empty — nothing would flow")
    for name, spec in (pipelines.items() if isinstance(pipelines, dict) else []):
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
                    errors.append(
                        f"pipeline `{name}`: batch must be LAST (found `{used[-1]}`)"
                    )

    for comp in service.get("extensions") or []:
        if str(comp) not in defined["extensions"]:
            errors.append(f"service.extensions uses `{comp}`, which is not defined")

for e in errors:
    print(f"✗ otel-check: {e}", file=sys.stderr)
sys.exit(1 if errors else 0)
PY

ok otel-check "$CONFIG is structurally valid"
