#!/usr/bin/env bash
# ============================================================================
# HOGOPLUS-FS — latency A/B: OLD (Emergent) vs NEW (Mumbai).
# Run from your laptop / phone hotspot (i.e. an Indian network) to get a real
# before/after number. Times /api/health (unauth) and /api/auth/me (authed).
#
#   bash latency_check.sh <OLD_URL> <NEW_URL> <PHONE> [OTP] [N]
#   e.g. bash latency_check.sh \
#        https://hogo-backend-phase1.preview.emergentagent.com \
#        https://api.hogoplus.com +919000000500 123456 15
#
# PHONE/OTP: use a demo account (e.g. +919000000500 / 123456). Read-only.
# Requires: bash, curl, python3.
# ============================================================================
set -euo pipefail

OLD_URL="${1:?need OLD_URL}"; NEW_URL="${2:?need NEW_URL}"
PHONE="${3:?need PHONE}"; OTP="${4:-123456}"; N="${5:-15}"

strip() { echo "${1%/}"; }
OLD_URL="$(strip "$OLD_URL")"; NEW_URL="$(strip "$NEW_URL")"

# median of N timed GETs (seconds -> ms), $1=url $2=auth-header-or-empty
timed() {
  local url="$1" auth="$2" i t times=()
  for ((i=0;i<N;i++)); do
    if [[ -n "$auth" ]]; then
      t=$(curl -s -o /dev/null -H "$auth" -w '%{time_total}' "$url")
    else
      t=$(curl -s -o /dev/null -w '%{time_total}' "$url")
    fi
    times+=("$t")
  done
  printf '%s\n' "${times[@]}" | python3 -c "import sys;v=sorted(float(x)*1000 for x in sys.stdin);print(f'{v[len(v)//2]:.0f}')"
}

login() {  # echo access token or empty
  curl -s -X POST "$1/api/auth/verify-otp" -H 'Content-Type: application/json' \
    -d "{\"phone\":\"$PHONE\",\"otp\":\"$OTP\"}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true
}

echo "Warming up + logging in on both backends (N=$N samples each)..."
OLD_TOK="$(login "$OLD_URL")"; NEW_TOK="$(login "$NEW_URL")"
[[ -z "$OLD_TOK" ]] && echo "  WARN: login failed on OLD ($OLD_URL)"
[[ -z "$NEW_TOK" ]] && echo "  WARN: login failed on NEW ($NEW_URL)"

H_OLD="$(timed "$OLD_URL/api/health" "")"
H_NEW="$(timed "$NEW_URL/api/health" "")"
M_OLD="$([[ -n "$OLD_TOK" ]] && timed "$OLD_URL/api/auth/me" "Authorization: Bearer $OLD_TOK" || echo 'n/a')"
M_NEW="$([[ -n "$NEW_TOK" ]] && timed "$NEW_URL/api/auth/me" "Authorization: Bearer $NEW_TOK" || echo 'n/a')"

echo ""
printf '%-26s %12s %12s\n' "endpoint (median ms)" "OLD" "NEW"
printf '%-26s %12s %12s\n' "--------------------------" "------------" "------------"
printf '%-26s %12s %12s\n' "/api/health"   "$H_OLD" "$H_NEW"
printf '%-26s %12s %12s\n' "/api/auth/me"  "$M_OLD" "$M_NEW"
echo ""
echo "Lower NEW = closer to your users. Expect Mumbai ~20-40ms vs the far region ~300-500ms."
