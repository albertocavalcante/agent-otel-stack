default: check

# Run every repository check
check: leaks links refs paths trap-check lint fmt-check otel-check dash-check
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

# Fail if a README trap anchor is dead or the stated trap count has drifted
trap-check:
    @./tools/trap_check.py

# Structurally validate both collector configs without needing the binary
otel-check:
    @./tools/otel_check.py

# Fail on dashboard JSON that will not bind to a provisioned datasource
dash-check:
    @./tools/dash-check.sh

# Fail if a documented Copilot setting has drifted from the installed VS Code.
# Depends on local machine state, so — like `pins` — deliberately NOT in `check`:
# on a machine without VS Code it can only warn and pass, and a gate that
# reports ✓ having verified nothing is this repo's own subject matter.
#
# `just` takes the LAST comment line as a recipe's description, so every recipe
# whose comment runs to a second line needs [doc] or `just --list` prints a
# sentence fragment. Three of them did.
[doc("Fail if a documented Copilot setting has drifted from the installed VS Code")]
copilot-check:
    @./tools/copilot_check.py

# Run the gates' own self-tests
test:
    @./tools/test_tools.py

# Static-analyse every shell script
lint:
    @./tools/lint.sh

# Rewrite every shell script in the canonical format
fmt:
    @./tools/fmt.sh

# Fail if any shell script deviates from the canonical format
fmt-check:
    @./tools/fmt.sh --check

# Render otel/env/claude-code.env as a settings.json `env` block, for pasting
# into ~/.claude/settings.json. Prints; never writes. `--include-optional` adds
# the settings that file deliberately ships off.
[doc("Render claude-code.env as a settings.json `env` block. Prints, never writes")]
settings *args:
    @./tools/settings_render.py {{ args }}

# Verify Claude Code's telemetry surface on THIS machine — console exporter,
# no collector and no container. Makes two billed calls.
[doc("Verify Claude Code's telemetry surface on THIS machine. Makes two billed calls")]
smoke prompt='reply with exactly: ok':
    @./tools/smoke.sh {{ quote(prompt) }}

# Verify Copilot's telemetry surface on THIS machine — no seat, no API calls.
# Pass a dump the file exporter produced to report what it actually contains.
[doc("Verify Copilot's telemetry surface on THIS machine — no seat, no API calls")]
copilot-smoke dump='':
    @./tools/copilot_smoke.py {{ quote(dump) }}

# Report what is in Copilot's local SQLite span store. Read-only, never writes.
copilot-traces:
    @./tools/copilot_traces.py

# Report whether this ACCOUNT has a Copilot seat. The third leg: copilot-check
# reads the bundle, copilot-traces reads the local store, and neither can see
# the thing that stops both producing data. Needs network and a credential, so
# — like `pins` — deliberately NOT in `check`.
[doc("Report whether this account has a Copilot seat. Needs network and a credential")]
copilot-account:
    @./tools/copilot_account.py

# Fail if a compose image digest is not its tag's manifest list. Needs network,
# so deliberately NOT in `check`.
[doc("Fail if a compose image digest is not its tag's manifest list. Needs network")]
pins:
    @./tools/pins_check.py

# Generate .env with a local dev token. Idempotent; never overwrites a token.
stack-init:
    @./tools/stack.sh init

# Bring the local stack up and wait until every service is actually serving
up:
    @./tools/stack.sh up

# Stop the stack. `just down --volumes` also drops the agent's queue.
down *args:
    @./tools/stack.sh down {{ args }}

# Post one span to the agent and prove it reaches Tempo
stack-check:
    @./tools/stack_probe.py

# Follow stack logs. `just logs collector-gateway` for one service.
logs *args:
    @./tools/stack.sh logs {{ args }}

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
