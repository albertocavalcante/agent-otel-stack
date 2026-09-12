#!/usr/bin/env bash
# tools/otel-check.sh — structurally validate the collector config without the
# collector. Run by `just otel-check`.
#
# `otelcol validate` needs the binary. These three are checkable from the YAML
# alone: a pipeline naming an undefined component (whose startup error reads
# like "my endpoint is wrong"), memory_limiter not first, batch not last.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

CONFIG="otel/collector.yaml"
[ -f "$CONFIG" ] || {
  ok otel-check "no collector config yet"
  exit 0
}

require_cmd python3

python3 - "$CONFIG" <<'PY'
import sys, re

path = sys.argv[1]
raw = open(path).read()

# Deliberately not PyYAML: this gate must run with nothing installed. The config
# is ours and its shape is fixed, so a small indentation-aware reader is enough
# and has no dependency. If this ever needs to handle arbitrary YAML, replace it
# with `uv run --with pyyaml` rather than growing this function.
def top_level_blocks(text):
    blocks, current, buf = {}, None, []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            if current:
                blocks[current] = buf
            current = line.split(":", 1)[0].strip()
            buf = []
        elif current:
            buf.append(line)
    if current:
        blocks[current] = buf
    return blocks

def names_at(lines, indent):
    """Component keys at a given indentation, e.g. the exporters under `exporters:`."""
    out = []
    for line in lines:
        stripped = line.lstrip()
        if len(line) - len(stripped) != indent or not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            out.append(stripped.split(":", 1)[0].strip())
    return out

blocks = top_level_blocks(raw)
errors = []

defined = {k: set(names_at(blocks.get(k, []), 2)) for k in
           ("receivers", "processors", "exporters", "extensions", "connectors")}

service = blocks.get("service")
if service is None:
    errors.append("no `service:` block — the collector has nothing to run")
else:
    text = "\n".join(service)
    # pipelines:\n    traces:\n      receivers: [otlp]\n      ...
    for pipeline, body in re.findall(
        r"^\s{4}(\w+(?:/\w+)?):\s*$((?:\n\s{6}.*)*)", text, re.M
    ):
        for kind in ("receivers", "processors", "exporters"):
            m = re.search(rf"^\s{{6}}{kind}:\s*\[(.*?)\]\s*$", body, re.M)
            if not m:
                if kind != "processors":
                    errors.append(f"pipeline `{pipeline}` declares no {kind}")
                continue
            used = [x.strip() for x in m.group(1).split(",") if x.strip()]
            for comp in used:
                if comp not in defined[kind]:
                    errors.append(
                        f"pipeline `{pipeline}` uses {kind[:-1]} `{comp}`, "
                        f"which is not defined under `{kind}:`"
                    )
            if kind == "processors" and used:
                if used[0] != "memory_limiter":
                    errors.append(
                        f"pipeline `{pipeline}`: memory_limiter must be FIRST "
                        f"(found `{used[0]}`) or the collector can OOM before it applies"
                    )
                if "batch" in used and used[-1] != "batch":
                    errors.append(
                        f"pipeline `{pipeline}`: batch must be LAST (found `{used[-1]}`)"
                    )

    for ext in re.findall(r"^\s{2}extensions:\s*\[(.*?)\]\s*$", text, re.M):
        for comp in (x.strip() for x in ext.split(",") if x.strip()):
            if comp not in defined["extensions"]:
                errors.append(f"service.extensions uses `{comp}`, which is not defined")

if errors:
    for e in errors:
        print(f"✗ otel-check: {e}", file=sys.stderr)
    sys.exit(1)
PY

ok otel-check "$CONFIG is structurally valid"
