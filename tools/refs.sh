#!/usr/bin/env bash
# tools/refs.sh — fail if a reference-style link is used but never defined,
# or defined but unused. Run by `just refs`.
#
# `links` only sees inline ](path) links. A reference link [text][id] whose
# [id]: definition is missing renders as literal text on GitHub rather than
# erroring, so it needs its own gate.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

failed=0
for f in $(md_files); do
  used=$({ grep -oE '\]\[[A-Za-z0-9_-]+\]' "$f" || true; } | sed -E 's/^\]\[(.*)\]$/\1/' | sort -u)
  defined=$({ grep -oE '^\[[A-Za-z0-9_-]+\]:' "$f" || true; } | sed -E 's/^\[(.*)\]:$/\1/' | sort -u)
  for id in $used; do
    if ! printf '%s\n' "$defined" | grep -qx "$id"; then
      echo "✗ refs: $f uses [$id] but never defines it" >&2
      failed=1
    fi
  done
  for id in $defined; do
    if ! printf '%s\n' "$used" | grep -qx "$id"; then
      echo "✗ refs: $f defines [$id] but never uses it" >&2
      failed=1
    fi
  done
done
[ "$failed" -eq 0 ] || exit 1
ok refs "every reference-style link resolves"
