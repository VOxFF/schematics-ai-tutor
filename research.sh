#!/usr/bin/env bash
# Learner experience research records (docs/design.md §5), on the Fly volume at /data/research.
# Needs flyctl, logged in with access to the app. Nothing serves these files over HTTP.
#   ./research.sh list                 learners on the server, with record sizes
#   ./research.sh pull                 download everything into ./research (gitignored)
#   ./research.sh delete <learner_id>  remove one learner's records on the server
#   ./research.sh experience [--pull]  the 🔔 feedback conversations as research/experience.md
set -euo pipefail

APP="${FLY_APP:-schematics-ai-tutor}"
REMOTE=/data/research
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOCAL="$ROOT/research"

remote() { fly ssh console -a "$APP" -C "sh -c '$1'"; }

case "${1:-}" in
  list)
    remote "cd $REMOTE 2>/dev/null && du -sh -- * 2>/dev/null || echo \"no records yet\""
    ;;
  pull)
    # A tar stream as base64 text, so the ssh terminal can't mangle it.
    archive="$(mktemp)"
    remote "if [ -d $REMOTE ]; then tar czf - -C /data research | base64; fi" | tr -d '\r' | base64 -d > "$archive"
    if [ ! -s "$archive" ]; then
      echo "no records yet"
    else
      mkdir -p "$LOCAL"
      tar xzf "$archive" -C "$ROOT"
      echo "pulled into $LOCAL: $(find "$LOCAL" -name '*.jsonl' | wc -l | tr -d ' ') file(s)"
    fi
    rm -f "$archive"
    ;;
  delete)
    id="${2:-}"
    if ! [[ "$id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
      echo "usage: ./research.sh delete <learner_id>  (a UUID)" >&2
      exit 1
    fi
    remote "rm -rf $REMOTE/$id && echo deleted $id"
    ;;
  experience)
    [ "${2:-}" = "--pull" ] && "$0" pull
    python3 "$ROOT/scripts/research_experience.py" "$LOCAL"
    ;;
  *)
    sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
