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
  # CommonMark allows a quoted title after the destination. Without stripping
  # it, the existence test looks for a filename ending in a double quote.
  # (No example written here: `just paths` would read it as a real reference.)
  target="${target%% *}"
  target="${target%%#*}"
  [ -z "$target" ] && continue
  if [ ! -e "$(dirname "$file")/$target" ]; then
    echo "✗ broken link: $file -> $target" >&2
    failed=1
  fi
done < <(
  # git-scoped, matching refs.sh. `grep -r .` would walk node_modules/ and
  # every gitignored markdown file and report broken links in other people's
  # vendored docs.
  while IFS= read -r md; do
    { grep -oE '\]\([^)]+\)' "$md" || true; } |
      sed -E "s|\]\(([^)]*)\)|$md:\1|"
  done < <(md_files)
)
[ "$failed" -eq 0 ] || exit 1
ok links "all relative links resolve"
