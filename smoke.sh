#!/usr/bin/env bash
# Smoke test of a deployed app: health, page, assets, HTTPS redirect, WebSocket upgrade. No Claude calls.
# Usage: ./smoke.sh [url]      (defaults to the production URL; see docs/deployment.md)
# Run by .github/workflows/deploy.yml after every deploy.
set -euo pipefail

URL="${1:-https://schematics-ai-tutor.fly.dev}"
URL="${URL%/}"
failures=0

pass() { echo "ok    $1"; }
fail() { echo "FAIL  $1" >&2; failures=$((failures + 1)); }

# A fresh deploy may still be starting: wait up to ~60 s for the health check.
health=""
for _ in $(seq 1 12); do
  health="$(curl -sf -m 10 "$URL/api/health" || true)"
  [ "$health" = '{"status":"ok"}' ] && break
  sleep 5
done
[ "$health" = '{"status":"ok"}' ] && pass "GET /api/health" || fail "GET /api/health: '${health}'"

page="$(curl -sf -m 10 "$URL/" || true)"
if grep -q "<title>Schematics AI Tutor</title>" <<< "$page"; then
  pass "GET / serves the app"
else
  fail "GET / does not serve the app"
fi

asset="$(grep -o '/assets/[^"]*\.js' <<< "$page" | head -1 || true)"
if [ -n "$asset" ] && [ "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$URL$asset")" = 200 ]; then
  pass "GET $asset"
else
  fail "JS asset '${asset}' not served"
fi

if [[ "$URL" == https://* ]]; then
  code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://${URL#https://}/")"
  [ "$code" = 301 ] && pass "http:// redirects to https://" || fail "http:// returned $code, expected 301"
fi

# The upgrade succeeds and the connection stays open, so curl times out (exit 28) after the 101.
code="$(curl -s --http1.1 -o /dev/null -m 5 -w '%{http_code}' \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "$URL/ws/session" || true)"
[ "$code" = 101 ] && pass "WebSocket upgrade on /ws/session" || fail "WebSocket upgrade returned $code, expected 101"

if [ "$failures" -gt 0 ]; then
  echo "smoke: $failures failure(s) at $URL" >&2
  exit 1
fi
echo "smoke: ok ($URL)"
