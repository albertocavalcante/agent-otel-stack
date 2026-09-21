default: check

# Run every repository check
check: leaks links refs paths lint fmt-check otel-check dash-check copilot-check
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

# Fail if a comment points at a repo file that does not exist
paths:
    @./tools/paths.py

# Structurally validate otel/collector.yaml without needing the collector binary
otel-check:
    @./tools/otel_check.py

# Fail on dashboard JSON that will not bind to a provisioned datasource
dash-check:
    @./tools/dash-check.sh

# Fail if a documented Copilot setting has drifted from the installed VS Code
copilot-check:
    @./tools/copilot_check.py

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
# no collector and no container. Makes two billed calls.
smoke prompt='reply with exactly: ok':
    @./tools/smoke.sh {{ quote(prompt) }}

# Verify Copilot's telemetry surface on THIS machine — no seat, no API calls.
# Pass a dump the file exporter produced to report what it actually contains.
copilot-smoke dump='':
    @./tools/copilot_smoke.py {{ quote(dump) }}

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
