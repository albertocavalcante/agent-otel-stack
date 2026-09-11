#!/usr/bin/env bash
# tools/smoke.sh — prove Claude Code's telemetry surface on THIS machine, with no
# collector, no container and no disk. Run by `just smoke`.
#
# Every claim in docs/01-claude-code.md is checkable here in about thirty seconds
# using the `console` exporter. That matters because three of the caveats in this
# repo are version-bound, and because the trace finding is the one most likely to
# be doubted: Claude Code DOES emit spans, gated only by an env var, with no org
# allowlist and no server-side flag.
#
# Deliberately does NOT pass --bare. --bare forces credential resolution through
# ANTHROPIC_API_KEY; a plain `claude -p` uses whatever auth you already have.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

require_cmd claude

PROMPT="${1:-reply with exactly: ok}"
OUT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-otel-smoke.XXXXXX")"
trap 'rm -rf "$OUT_DIR"' EXIT

VERSION="$(claude --version 2>/dev/null | head -n1)"
echo
echo "claude version: ${VERSION:-unknown}"
echo "prompt:         $PROMPT"
echo

# --- pass 1: metrics + events ------------------------------------------------
# OTEL_METRIC_EXPORT_INTERVAL defaults to 60000ms. Without lowering it a correct
# setup prints nothing for a full minute and reads as broken.
echo "── pass 1: metrics + events ──────────────────────────────────────────"
CLAUDE_CODE_ENABLE_TELEMETRY=1 \
  OTEL_METRICS_EXPORTER=console \
  OTEL_LOGS_EXPORTER=console \
  OTEL_METRIC_EXPORT_INTERVAL=1000 \
  OTEL_LOGS_EXPORT_INTERVAL=1000 \
  claude -p "$PROMPT" >"$OUT_DIR/p1.out" 2>"$OUT_DIR/p1.err" || true
cat "$OUT_DIR/p1.out" "$OUT_DIR/p1.err" >"$OUT_DIR/p1.all"

METRICS=(
  claude_code.session.count
  claude_code.lines_of_code.count
  claude_code.pull_request.count
  claude_code.commit.count
  claude_code.cost.usage
  claude_code.token.usage
  claude_code.code_edit_tool.decision
  claude_code.active_time.total
)
seen=0
for m in "${METRICS[@]}"; do
  if grep -qF "$m" "$OUT_DIR/p1.all"; then
    printf '  ✓ %s\n' "$m"
    seen=$((seen + 1))
  else
    printf '  · %s (not emitted by this prompt)\n' "$m"
  fi
done
echo "  → $seen/${#METRICS[@]} documented metrics observed"

# A metric name appearing proves the pipeline works. Not every metric fires on a
# trivial prompt — commit.count and pull_request.count need a commit and a PR —
# so only the always-on ones are treated as required.
for required in claude_code.session.count claude_code.token.usage; do
  grep -qF "$required" "$OUT_DIR/p1.all" || die smoke "$required never appeared — telemetry is not reaching the exporter"
done

if grep -qF 'claude_code.api_request' "$OUT_DIR/p1.all"; then
  echo "  ✓ claude_code.api_request event present"
  grep -qF 'cost_usd' "$OUT_DIR/p1.all" &&
    echo "  ✓ …carries cost_usd (the only event with both tokens and cost)" ||
    warn smoke "api_request present but cost_usd absent — unexpected on a documented build"
else
  warn smoke "claude_code.api_request not observed (is OTEL_LOGS_EXPORTER reaching stderr?)"
fi

# --- pass 2: traces ----------------------------------------------------------
echo
echo "── pass 2: traces (beta) ─────────────────────────────────────────────"
CLAUDE_CODE_ENABLE_TELEMETRY=1 \
  CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1 \
  OTEL_TRACES_EXPORTER=console \
  OTEL_TRACES_EXPORT_INTERVAL=1000 \
  claude -p "$PROMPT" >"$OUT_DIR/p2.out" 2>"$OUT_DIR/p2.err" || true
cat "$OUT_DIR/p2.out" "$OUT_DIR/p2.err" >"$OUT_DIR/p2.all"

LIVE_SPANS=(claude_code.interaction claude_code.llm_request claude_code.tool)
live_seen=0
for s in "${LIVE_SPANS[@]}"; do
  if grep -qF "$s" "$OUT_DIR/p2.all"; then
    printf '  ✓ %s\n' "$s"
    live_seen=$((live_seen + 1))
  else
    printf '  · %s (not triggered by this prompt)\n' "$s"
  fi
done
if [ "$live_seen" -eq 0 ]; then
  warn smoke "no spans observed — tracing is beta; confirm CLAUDE_CODE_ENHANCED_TELEMETRY_BETA is honoured on $VERSION"
else
  echo "  → tracing works on this build, gated only by an env var"
fi

# --- pass 3: the negative assertion -----------------------------------------
# These four span names exist in the 2.1.220 bundle but every call site is gated
# on a function that is a hard-coded false. If one ever shows up here, the claim
# in docs/01 is wrong for your build and this gate is how you find out.
echo
echo "── pass 3: dead-code spans must NOT appear ───────────────────────────"
DEAD_SPANS=(
  claude_code.subagent.spawn
  claude_code.bash.subprocess
  claude_code.compaction
  claude_code.mcp.rpc
)
leaked=0
for s in "${DEAD_SPANS[@]}"; do
  if grep -qF "$s" "$OUT_DIR/p2.all"; then
    fail smoke "$s WAS emitted — the dead-code reading is wrong on $VERSION, update docs/01"
    leaked=1
  else
    printf '  ✓ %s absent, as expected\n' "$s"
  fi
done
[ "$leaked" -eq 0 ] || exit 1

echo
ok smoke "telemetry surface verified on ${VERSION:-unknown} — no collector required"
echo
echo "Nothing was written outside $OUT_DIR, which is now removed."
