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
# The first version of this check matched `<interpreter> -<anything>`, which
# was wrong in both directions at once: it flagged `python3 --version`, and it
# missed `PY=python3; $PY -c`. So it now looks for the interpreter NAME at all,
# anywhere outside a comment, and allows only the two forms that do not run it:
# `command -v` and `require_cmd`.
#
# Comments are stripped first, or every explanatory paragraph in this file
# trips its own gate.
# Written with a character class per name so this file does not match its own
# pattern — the same trick LEAK_PATTERN uses in lib/common.sh, and for the same
# reason. `pytho[n]3?` matches "python3"; the literal text does not.
#
# The name must sit in COMMAND position — start of line, or after whitespace,
# `;`, `&`, `|`, `(`, `=` or `/` — and be followed by whitespace, `<` or end of
# line. Without that last part the pattern also matched the bash array
# `${python[@]}` in this very file, since the `3` is optional; without `/` it
# missed `/usr/bin/python3 -c`, which the committed self-tests caught after a
# hand-run drill list had silently stopped covering it.
INTERPRETERS='pytho[n]3?|rub[y]|per[l]|nod[e]|osascrip[t]'

embedded=0
for f in "${shell[@]}"; do
  if sed -e 's/[[:space:]]#.*$//' -e '/^[[:space:]]*#/d' "$f" |
    grep -nE "(^|[[:space:];&|(=/])($INTERPRETERS)([[:space:]<]|$)" |
    grep -vE '(command -v|require_cmd)[[:space:]]+('"$INTERPRETERS"')'; then
    echo "✗ lint: $f names an interpreter — move that work to its own file" >&2
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

mapfile -t py < <(py_files)
if [ "${#py[@]}" -eq 0 ]; then
  echo "✓ lint: no Python files to check"
elif ! ruff check --quiet "${py[@]}"; then
  echo "✗ lint: ruff reported issues above" >&2
  exit 1
fi

echo "✓ lint: ${#shell[@]} shell + ${#py[@]} Python file(s) clean"
