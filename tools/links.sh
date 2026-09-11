#!/usr/bin/env bash
# tools/links.sh — fail on broken relative links between documents. Run by
# `just links`.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

failed=0
while IFS= read -r line; do
  file="${line%%:*}"
  target="${line#*:}"
  case "$target" in http* | \#* | mailto:*) continue ;; esac
  target="${target%%#*}"
  [ -z "$target" ] && continue
  if [ ! -e "$(dirname "$file")/$target" ]; then
    echo "✗ broken link: $file -> $target" >&2
    failed=1
  fi
done < <(grep -rIoE '\]\([^)]+\)' --include='*.md' . | sed -E 's/\]\(([^)]*)\)/\1/')
[ "$failed" -eq 0 ] || exit 1
ok links "all relative links resolve"
