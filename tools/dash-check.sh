#!/usr/bin/env bash
# tools/dash-check.sh — reject dashboard JSON that will not bind to a provisioned
# datasource. Run by `just dash-check`.
#
# This gate exists because of one specific, extremely common failure. When you
# export a dashboard with "Export for sharing externally", or download one from
# grafana.com, the JSON gains an `__inputs` block declaring DS_PROMETHEUS and
# every panel becomes "datasource": "${DS_PROMETHEUS}". The *import UI* resolves
# that by prompting you. The *file provisioner does not* — it performs no
# substitution, so every panel renders:
#
#     Datasource named ${DS_PROMETHEUS} was not found
#
# and the dashboard looks broken for a reason that is invisible in the diff.
# Tracked upstream since 2018: grafana/grafana#10786.
#
# The second half of the trap is the datasource side: if `uid:` is not pinned in
# provisioning, Grafana mints a random one on first provision and persists it, so
# a committed dashboard can never reference it and a wiped volume changes it.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

require_cmd jq

DASH_DIR="dashboards"
DS_FILE="dashboards/provisioning/datasources.yaml"

shopt -s nullglob
dashboards=("$DASH_DIR"/*.json)
if [ "${#dashboards[@]}" -eq 0 ]; then
  ok dash-check "no dashboards yet"
  exit 0
fi

if [ ! -f "$DS_FILE" ]; then
  fail dash-check "$DS_FILE is missing — dashboards cannot bind without provisioned datasources"
  exit 1
fi

# Provisioned UIDs. Parsed with grep rather than a YAML library so this gate has
# no dependency beyond jq; the file is ours and its shape is fixed.
mapfile -t provisioned < <(grep -oE '^[[:space:]]*uid:[[:space:]]*[A-Za-z0-9_-]+' "$DS_FILE" |
  sed -E 's/^[[:space:]]*uid:[[:space:]]*//')

if [ "${#provisioned[@]}" -eq 0 ]; then
  fail dash-check "$DS_FILE pins no uid: — Grafana will mint random UIDs and nothing will bind"
  exit 1
fi

# Grafana enforces this since v12 (failWrongDSUID on by default): a valid uid is
# alphanumeric plus dash and underscore, max 40 chars. The docs disagree with
# themselves about underscore, so we require the stricter [a-z0-9-].
for uid in "${provisioned[@]}"; do
  if ! printf '%s' "$uid" | grep -qE '^[a-z0-9-]{1,40}$'; then
    fail dash-check "datasource uid '$uid' is not [a-z0-9-] and <=40 chars — Grafana v12+ rejects it"
    exit 1
  fi
done

fails=0
for f in "${dashboards[@]}"; do
  if ! jq empty "$f" 2>/dev/null; then
    fail dash-check "$f is not valid JSON"
    fails=1
    continue
  fi

  # 1. The export-for-sharing artefacts.
  if jq -e 'has("__inputs") or has("__requires")' "$f" >/dev/null 2>&1; then
    fail dash-check "$f has __inputs/__requires — strip them; the file provisioner ignores both"
    fails=1
  fi

  # 2. Any surviving template token, anywhere in the document.
  if jq -e 'tostring | test("\\$\\{DS_")' "$f" >/dev/null 2>&1; then
    fail dash-check "$f still contains \${DS_...} — the provisioner does not substitute it"
    fails=1
  fi

  # 3. Every datasource reference must be an explicit {type, uid} object, and the
  #    uid must be one we actually provision. `..` walks the whole document, which
  #    is the point: targets[], templating.list[] and annotations.list[] are the
  #    ones people miss when doing this by hand.
  bad_shape=$(jq -r '
    [ .. | objects | select(has("datasource")) | .datasource
      | select(. != null)
      | select((type != "object") or (has("uid") | not)) ]
    | length' "$f")
  if [ "$bad_shape" -gt 0 ]; then
    fail dash-check "$f has $bad_shape datasource ref(s) that are not an explicit {type, uid} object"
    fails=1
  fi

  mapfile -t used < <(jq -r '[.. | objects | select(has("datasource")) | .datasource
    | select(type == "object") | .uid | select(. != null)] | unique[]' "$f")
  for uid in "${used[@]}"; do
    # A dashboard variable legitimately reads ${ds} style refs; allow those through
    # and check only literal uids.
    case "$uid" in '${'*) continue ;; esac
    found=0
    for p in "${provisioned[@]}"; do [ "$uid" = "$p" ] && found=1 && break; done
    if [ "$found" -eq 0 ]; then
      fail dash-check "$f references datasource uid '$uid', which $DS_FILE does not provision"
      fails=1
    fi
  done
done

[ "$fails" -eq 0 ] || exit 1
ok dash-check "${#dashboards[@]} dashboard(s) bind to provisioned datasources"
