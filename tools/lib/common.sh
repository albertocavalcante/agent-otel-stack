#!/usr/bin/env bash
# tools/lib/common.sh — shared shell helpers for the repository's `just`
# gates (leaks, links, refs, lint, fmt, ...).
#
# Source this, don't execute it:
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
#
# Every caller is expected to already be running under `set -euo pipefail`.
# This module backs the repo's own gates, not the measurement harness under
# measure/ — the two are independent concerns that happen to share a style,
# so this file must never source or depend on measure/lib/common.sh.

# Resolve this file's own directory ONCE, at source time, using BASH_SOURCE[0]
# of *this* file (not a caller's). This is what makes repo_root() work no
# matter which script sourced common.sh or what the caller's cwd is.
_TOOLS_COMMON_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# repo_root — absolute path to the repository root, resolved relative to this
# file's own location. Never hard-code a path here.
repo_root() {
  (cd "$_TOOLS_COMMON_SH_DIR/../.." && pwd)
}

# ok "name" "msg"   → "✓ name: msg" on stdout
# warn "name" "msg" → "! name: msg" on stderr, exit status untouched
# fail "name" "msg" → "✗ name: msg" on stderr
# die "name" "msg"  → fail, then exit 1
ok() {
  printf '✓ %s: %s\n' "$1" "$2"
}

# A check that completed but could not conclude is not a failure — it must still
# be visibly distinct from one that passed. `just smoke` leans on this: a metric
# that simply wasn't triggered by a trivial prompt is not a broken pipeline.
warn() {
  printf '! %s: %s\n' "$1" "$2" >&2
}

fail() {
  printf '✗ %s: %s\n' "$1" "$2" >&2
}

die() {
  fail "$1" "$2"
  exit 1
}

# require_cmd <cmd> — refuse to run rather than half-run and report a
# misleading result.
require_cmd() {
  command -v "$1" >/dev/null 2>&1 ||
    die "require_cmd" "'$1' not found in PATH — install it and re-run"
}

# LEAK_PATTERN — personal paths and credential-shaped strings that must never
# be committed. Volume and home patterns are deliberately generic: they must
# catch any contributor's machine, not one author's. They are also written so
# this file does not match its own pattern -- a character class cannot match
# the literal '[' that starts it.
export LEAK_PATTERN='/Volumes/[A-Za-z0-9_-]+/|/Users/[a-z]|/home/[a-z]|ghp_[A-Za-z0-9]{20}|gho_[A-Za-z0-9]{20}|github[_]pat[_]|sk[-]ant[-]|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

# md_files — every Markdown file the repo will ship, one per line.
#
# Includes untracked-but-not-ignored files. A plain `git ls-files` covers only
# tracked paths, so a brand-new document passed `refs` and `sources` vacuously
# until the moment it was staged — a green check that proved nothing.
md_files() {
  git ls-files --cached --others --exclude-standard '*.md'
}

# sh_files — every shell script the repo will ship, one per line.
# Same untracked-inclusive rule as md_files, for the same reason.
sh_files() {
  git ls-files --cached --others --exclude-standard '*.sh'
}
