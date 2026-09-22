#!/usr/bin/env bash
# tools/fmt.sh — rewrite every script in the canonical format, in both
# languages. With --check, fail instead if any script deviates from it. Run by
# `just fmt` and `just fmt-check`.
#
# Shell is shfmt -i 2 -ci. Python is ruff format, which is 4-space and offers no
# indent option — so the two do not match, and are not meant to.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

# Hand-rolled rather than require_cmd so the message can name the formula.
require_formatters() {
  local gate=$1
  if ! command -v shfmt >/dev/null 2>&1; then
    echo "✗ $gate: shfmt not installed (brew install shfmt)" >&2
    exit 1
  fi
  if ! command -v ruff >/dev/null 2>&1; then
    echo "✗ $gate: ruff not installed (brew install ruff)" >&2
    exit 1
  fi
}

mapfile -t shell < <(sh_files)
mapfile -t py < <(py_files)

if [ "${1:-}" = "--check" ]; then
  require_formatters fmt-check

  if [ "${#shell[@]}" -gt 0 ]; then
    # Two conditions: shfmt -d exits non-zero on a diff, and this also catches
    # the case where it exits 0 having emitted one anyway.
    if ! diff=$(shfmt -i 2 -ci -d "${shell[@]}") || [ -n "$diff" ]; then
      printf '%s\n' "$diff"
      echo "✗ fmt-check: run \`just fmt\` to fix the above" >&2
      exit 1
    fi
  fi

  if [ "${#py[@]}" -gt 0 ] && ! ruff format --check --quiet --diff "${py[@]}"; then
    echo "✗ fmt-check: run \`just fmt\` to fix the above" >&2
    exit 1
  fi

  echo "✓ fmt-check: ${#shell[@]} shell + ${#py[@]} Python file(s) correctly formatted"
  exit 0
fi

require_formatters fmt

if [ "${#shell[@]}" -gt 0 ]; then
  shfmt -i 2 -ci -w "${shell[@]}"
fi
if [ "${#py[@]}" -gt 0 ]; then
  ruff format --quiet "${py[@]}"
fi

echo "✓ fmt: formatted ${#shell[@]} shell + ${#py[@]} Python file(s)"
