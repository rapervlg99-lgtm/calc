#!/usr/bin/env bash
set -euo pipefail

# Smoke against a running ozm-backend (compose local maps 8080).
BASE_URL=${BASE_URL:-http://localhost:8080}

curl -sf "$BASE_URL/healthz" >/dev/null
curl -sf "$BASE_URL/api/v1/dicts" >/dev/null

payload='{
  "objectName": "smoke",
  "address": "Москва",
  "consent": true,
  "frDurability": "2",
  "groups": [{
    "title": "G1",
    "quantity": 1,
    "elements": [{
      "title": "B1",
      "shape": "I-beam_",
      "dims": {"h": 200, "b": 100, "s": 5.6, "t": 8.5, "R": 12},
      "frType": "1",
      "htLevel": 60,
      "sides": {"left": true, "top": true, "right": true, "bottom": true},
      "lengthM": 6,
      "quantity": 1,
      "coat": "1",
      "method": "1"
    }]
  }]
}'

curl -sf -H 'Content-Type: application/json' -d "$payload" "$BASE_URL/api/v1/calc" >/dev/null

# OCR /ext optional
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/ext/profiles" || true)
if [ "$code" = "404" ]; then
  echo "ext not mounted (OCR disabled) - ok"
elif [ "$code" = "401" ]; then
  curl -sf -H "Authorization: Bearer smoke" "$BASE_URL/api/v1/ext/profiles" >/dev/null
  echo "ext ok"
else
  echo "unexpected /ext status without auth: $code" >&2
  exit 1
fi

echo "smoke ok"
