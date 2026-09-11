#!/usr/bin/env bash
# tools/leaks.sh — fail if personal paths or credential-shaped strings would
# be committed. Run by `just leaks`.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

# Include set covers every text file class in the repo. The extensionless
# `justfile` and the YAML configs were outside the gate in an earlier repo, which
# is exactly where the first real leak was found.
#
# `*.env` matters more here than anywhere else: this repo's whole subject is
# telemetry export, and the documented way to authenticate a collector is
# OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>. An env file is the
# first place someone will paste a real one.
#
# .git is excluded because grep -r does not read .gitignore and would otherwise
# scan pack files; the rest are build caches that would drown the signal.
if grep -rInE "$LEAK_PATTERN" \
  --exclude-dir='.venv' --exclude-dir='.git' \
  --exclude-dir='__pycache__' --exclude-dir='.pytest_cache' --exclude-dir='.ruff_cache' \
  --include='*.md' --include='*.json' --include='*.sh' --include='*.py' --include='*.env' \
  --include='*.toml' --include='*.yaml' --include='*.yml' --include='justfile' .; then
  fail leaks "personal path or credential-shaped string found above"
  exit 1
fi
ok leaks "clean"
