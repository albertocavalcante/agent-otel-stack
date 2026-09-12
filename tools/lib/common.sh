#!/usr/bin/env bash
# tools/lib/common.sh — shared shell helpers for the repository's `just`
# gates (leaks, links, refs, lint, fmt, ...).
#
# Source this, don't execute it:
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
#
# Every caller is expected to already be running under `set -euo pipefail`.
#
# bash 4+ is required: these gates use `mapfile`, and macOS ships 3.2.57 at
# /bin/bash. Homebrew's bash is found via `env bash`, but a trimmed PATH or a
# minimal CI image is not, and the failure is a bare `mapfile: command not
# found` rather than anything diagnosable.
if [ "${BASH_VERSINFO[0]:-0}" -lt 4 ]; then
  printf '✗ %s: bash 4+ required, found %s (macOS ships 3.2 at /bin/bash)\n' \
    "${0##*/}" "${BASH_VERSION:-unknown}" >&2
  exit 1
fi

# Resolved from BASH_SOURCE[0] of *this* file, so repo_root() is independent of
# the caller's cwd.
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

# Completed but inconclusive is not failure, and must not look like success.
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
# this file does not match its own pattern — a character class cannot match
# the literal '[' that starts it.
export LEAK_PATTERN='/Volumes/[A-Za-z0-9_-]+/|/Users/[a-z]|/home/[a-z]|ghp_[A-Za-z0-9]{20}|gho_[A-Za-z0-9]{20}|github[_]pat[_]|sk[-]ant[-]|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

# md_files — every Markdown file the repo will ship, one per line.
#
# Includes untracked-but-not-ignored files. A plain `git ls-files` covers only
# tracked paths, so a brand-new document passed `refs` vacuously
# until the moment it was staged — a green check that proved nothing.
md_files() {
  git ls-files --cached --others --exclude-standard '*.md'
}

# sh_files — every shell script the repo will ship, one per line.
# Same untracked-inclusive rule as md_files, for the same reason.
sh_files() {
  git ls-files --cached --others --exclude-standard '*.sh'
}
