#!/usr/bin/env bash
# tools/leaks.sh — fail if personal paths or credential-shaped strings would
# be committed. Run by `just leaks`.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

# The extensionless `justfile` and the YAML configs are easy to leave outside a
# gate like this; `*.env` is where an OTLP auth header would actually get pasted.
#
# grep -r does not read .gitignore, so the excludes have to be explicit.
if grep -rInE "$LEAK_PATTERN" \
  --exclude-dir='.venv' --exclude-dir='.git' \
  --exclude-dir='__pycache__' --exclude-dir='.pytest_cache' --exclude-dir='.ruff_cache' \
  --include='*.md' --include='*.json' --include='*.sh' --include='*.py' --include='*.env' \
  --include='*.toml' --include='*.yaml' --include='*.yml' --include='justfile' .; then
  fail leaks "personal path or credential-shaped string found above"
  exit 1
fi
ok leaks "clean"
