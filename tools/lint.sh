#!/usr/bin/env bash
# tools/lint.sh — static-analyse every script, in both languages. Run by
# `just lint`.
#
# Both halves matter. A third of this directory used to be Python embedded in
# heredocs, where shellcheck does not read it and ruff never sees it — two
# linters running on every commit, and a blind spot between them that was
# holding two leaked file handles.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

if ! command -v shellcheck >/dev/null 2>&1; then
  echo "✗ lint: shellcheck not installed (brew install shellcheck)" >&2
  exit 1
fi
if ! command -v ruff >/dev/null 2>&1; then
  echo "✗ lint: ruff not installed (brew install ruff)" >&2
  exit 1
fi

mapfile -t shell < <(sh_files)
if [ "${#shell[@]}" -eq 0 ]; then
  echo "✓ lint: no shell scripts to check"
elif ! shellcheck -S warning "${shell[@]}"; then
  echo "✗ lint: shellcheck reported issues above" >&2
  exit 1
fi

mapfile -t python < <(py_files)
if [ "${#python[@]}" -eq 0 ]; then
  echo "✓ lint: no python files to check"
elif ! ruff check --quiet "${python[@]}"; then
  echo "✗ lint: ruff reported issues above" >&2
  exit 1
fi

echo "✓ lint: ${#shell[@]} shell + ${#python[@]} python file(s) clean"
