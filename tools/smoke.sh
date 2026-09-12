#!/usr/bin/env bash
# tools/smoke.sh — verify Claude Code's telemetry surface on this machine
# without a collector or a container. Run by `just smoke`.
#
# Verifies the README's claims against the build in front of you, using the
# `console` exporter. Three of those claims are version-bound.
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

VERSION="$(claude --version 2>/dev/null | head -n1 || true)"
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
cat "$OUT_DIR/p1.out" "$OUT_DIR/p1.err" >"$OUT_DIR/p1.raw"
# The model's reply lands in this blob too, so a prompt that merely NAMES a
# metric would satisfy every assertion below with no telemetry at all. Drop any
# line echoing the prompt before asserting on it.
grep -vF -- "$PROMPT" "$OUT_DIR/p1.raw" >"$OUT_DIR/p1.all" || true

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
  OTEL_METRICS_EXPORTER=none \
  OTEL_LOGS_EXPORTER=none \
  OTEL_TRACES_EXPORT_INTERVAL=1000 \
  claude -p "$PROMPT" >"$OUT_DIR/p2.out" 2>"$OUT_DIR/p2.err" || true
cat "$OUT_DIR/p2.out" "$OUT_DIR/p2.err" >"$OUT_DIR/p2.raw"
grep -vF -- "$PROMPT" "$OUT_DIR/p2.raw" >"$OUT_DIR/p2.all" || true

LIVE_SPANS=(claude_code.interaction claude_code.llm_request claude_code.tool claude_code.hook)
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
# These four span names appear in the v2.1.220 bundle, but every call site is
# gated on a function that is a hard-coded false there, so none should emit.
# Method: string extraction from the shipped bundle. They are absent from the
# documented span hierarchy in code.claude.com/docs/en/monitoring-usage.
#
# This WARNS rather than fails. If Anthropic enables them, that is a vendor
# improvement, and a repo whose flagship command turns red on someone else's
# feature release is a repo nobody runs twice.
echo
echo "── pass 3: dead-code spans must NOT appear ───────────────────────────"
if [ "$live_seen" -eq 0 ]; then
  warn smoke "pass 3 skipped — pass 2 produced no span output, so absence proves nothing"
  echo
  ok smoke "metrics verified on ${VERSION:-unknown}; traces inconclusive"
  exit 0
fi
DEAD_SPANS=(
  claude_code.subagent.spawn
  claude_code.bash.subprocess
  claude_code.compaction
  claude_code.mcp.rpc
)
leaked=0
for s in "${DEAD_SPANS[@]}"; do
  if grep -qF "$s" "$OUT_DIR/p2.all"; then
    warn smoke "$s emitted on $VERSION — dormant on 2.1.220, so this build enables it; the README needs updating"
    leaked=1
  else
    printf '  ✓ %s absent, as expected\n' "$s"
  fi
done
if [ "$leaked" -ne 0 ]; then
  echo "  → not a failure: newer builds may enable these."
fi

echo
ok smoke "telemetry surface verified on ${VERSION:-unknown} — no collector required"
