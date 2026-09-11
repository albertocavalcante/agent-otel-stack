default: check

# Run every repository check
check: leaks links refs lint fmt-check otel-check dash-check
    @echo "✓ all checks passed"

# Fail if personal paths or credential-shaped strings would be committed
leaks:
    @./tools/leaks.sh

# Fail on broken relative links between documents
links:
    @./tools/links.sh

# Fail if a reference-style link is used but never defined
refs:
    @./tools/refs.sh

# Structurally validate otel/collector.yaml without needing the collector binary
otel-check:
    @./tools/otel-check.sh

# Fail on dashboard JSON that will not bind to a provisioned datasource
dash-check:
    @./tools/dash-check.sh

# Static-analyse every shell script
lint:
    @./tools/lint.sh

# Rewrite every shell script in the canonical format
fmt:
    @./tools/fmt.sh

# Fail if any shell script deviates from the canonical format
fmt-check:
    @./tools/fmt.sh --check

# Verify Claude Code's telemetry surface on THIS machine — console exporter,
# no collector, no container, no disk. Costs one trivial prompt.
smoke prompt='reply with exactly: ok':
    @./tools/smoke.sh '{{ prompt }}'

# Word count and link count per document
stats:
    #!/usr/bin/env bash
    set -euo pipefail
    printf '%-40s %8s %8s\n' DOCUMENT WORDS LINKS
    total=0
    for f in *.md docs/*.md; do
      [ -e "$f" ] || continue
      w=$(wc -w <"$f" | tr -d ' ')
      c=$( { grep -o 'https\?://' "$f" || true; } | wc -l | tr -d ' ')
      printf '%-40s %8s %8s\n' "$f" "$w" "$c"
      total=$((total + w))
    done
    printf '%-40s %8s\n' TOTAL "$total"
