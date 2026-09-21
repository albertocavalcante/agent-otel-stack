#!/usr/bin/env bash
# tools/links.sh — fail on broken relative links between documents. Run by
# `just links`.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

# macOS resolves a case-mismatched path that GitHub's case-sensitive storage
# 404s, so [ -e ] is not enough. `find -name` matches case-sensitively even on
# APFS, so walk every component and require an exact listing at each level.
case_exact() {
  local remaining="$1" dir="" comp
  case "$remaining" in /*) dir="/" ;; *) dir="." ;; esac
  while [ -n "$remaining" ]; do
    comp="${remaining%%/*}"
    if [ "$remaining" = "$comp" ]; then remaining=""; else remaining="${remaining#*/}"; fi
    if [ -z "$comp" ] || [ "$comp" = "." ]; then
      continue
    fi
    # `..` cannot be listed by name in its own parent; step up and move on.
    if [ "$comp" = ".." ]; then
      dir="$dir/.."
      continue
    fi
    find "$dir" -maxdepth 1 -mindepth 1 -name "$comp" 2>/dev/null | grep -q . || return 1
    dir="$dir/$comp"
  done
  return 0
}

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
  resolved="$(dirname "$file")/$target"
  if [ ! -e "$resolved" ]; then
    echo "✗ broken link: $file -> $target" >&2
    failed=1
  elif ! case_exact "$resolved"; then
    echo "✗ broken link (case): $file -> $target" >&2
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
