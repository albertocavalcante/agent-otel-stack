#!/usr/bin/env bash
# tools/dash-check.sh — reject dashboard JSON that will not bind to a provisioned
# datasource. Run by `just dash-check`.
#
# Exporting "for sharing externally", or downloading from grafana.com, adds an
# `__inputs` block and turns every panel into "datasource": "${DS_PROMETHEUS}".
# The import UI resolves that by prompting. The file provisioner does not, so
# every panel renders:
#
#     Datasource named ${DS_PROMETHEUS} was not found
#
# — invisible in the diff. Upstream: grafana/grafana#10786.
#
# The other half: an unpinned `uid:` in provisioning means Grafana mints a random
# one and persists it, so no committed dashboard can ever reference it.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
cd "$(repo_root)"

require_cmd jq
require_cmd yq

DASH_DIR="dashboards"
DS_FILE="dashboards/provisioning/datasources.yaml"

# Recursive: Grafana's file provider walks subdirectories, and the standard
# folder-per-product layout puts dashboards in them. A non-recursive glob
# silently skipped every one.
# Sorted: `find` returns filesystem order, so without this the error output
# would reorder between machines and between runs after a rename. A gate whose
# output is not byte-stable cannot be diffed.
dashboards=()
while IFS= read -r -d '' f; do dashboards+=("$f"); done < <(
  find "$DASH_DIR" -name '*.json' -not -path '*/provisioning/*' -print0 2>/dev/null |
    LC_ALL=C sort -z
)
if [ "${#dashboards[@]}" -eq 0 ]; then
  # Deliberately a pass, not a skip-with-a-wink. But say
  # so plainly, because until one exists every check below is untested at
  # so out loud, because an empty directory and a clean directory look
  # identical in a green log.
  ok dash-check "no dashboards to check (nothing under $DASH_DIR/)"
  exit 0
fi

if [ ! -f "$DS_FILE" ]; then
  fail dash-check "$DS_FILE is missing — dashboards cannot bind without provisioned datasources"
  exit 1
fi

# Harvested with yq, not grep. A character-class grep truncates `uid: prom.1`
# to `prom` — so a dashboard referencing `prom` passes here and then fails in
# Grafana, which is precisely the failure this gate exists to prevent. It also
# matched any `uid:` at any depth, including one nested under jsonData.
mapfile -t provisioned < <(yq -r '.datasources[] | select(has("uid")) | .uid' "$DS_FILE")

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
