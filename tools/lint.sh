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

# ONE LANGUAGE PER TOOL, and this is the assertion that keeps it true.
#
# A third of this directory was once Python inside heredocs, linted by nothing:
# heredoc bodies are invisible to the shell linter, and ruff never sees a .sh
# file at all. That was removed — and then came back within two commits, in
# tools/stack.sh, because removing it was a decision and nothing enforced it.
#
# (A comment line may not begin with the linter's own name here, or it is read
# as a directive. That is how this comment was first written, and it failed.)
#
# So: no interpreter may be invoked from a shell script. If a shell tool needs
# Python, it calls a .py file, which ruff can then actually read.
embedded=0
for f in "${shell[@]}"; do
  # Skip this gate's own pattern list, or it matches itself.
  [ "$f" = "tools/lint.sh" ] && continue
  if grep -nE '(^|[^[:alnum:]_])(python3?|ruby|perl|node|osascript)[[:space:]]+(-c|-e|-)' "$f"; then
    echo "✗ lint: $f embeds another language — move it to its own file" >&2
    embedded=1
  fi
done
[ "$embedded" -eq 0 ] || exit 1

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
