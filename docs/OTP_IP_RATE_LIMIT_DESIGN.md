# Design: IP-level rate limiting on /api/auth/send-otp

**Status: DESIGN ONLY — no code. For v1.0.19 review.**
Context: registration is opening to unknown numbers (ALLOW_NEW_REGISTRATION=true).
Existing protection is per-PHONE only (3/10 min, 45 s cooldown, verify lockout).
Gap: an attacker rotating phone numbers can drain SMS credits and probe the
employee table — per-phone limits never trigger.

## 1. Threat model

| Threat | Today | With this design |
|---|---|---|
| SMS-credit drain via rotating numbers | ❌ unbounded | ✅ per-IP + global caps |
| Phone enumeration (registration_closed vs OTP sent) | ❌ unbounded probing | ✅ per-IP cap + audit trail |
| Distributed (botnet) drain | ❌ | ⚠️ mitigated by global breaker (§4) |

## 2. IP extraction (must get this right first)

- Backend sits behind the ingress → use the **first untrusted hop** of
  `X-Forwarded-For` as set by OUR ingress (never trust the raw header blindly —
  clients can spoof prepended entries).
- Verify once on the production deployment which header the ingress sets
  (`X-Forwarded-For` / `X-Real-IP`) and whether it appends or replaces.
- Fallback: socket peer address. If extraction is uncertain, FAIL OPEN (no limit)
  and log — never lock out the whole factory on a proxy config change.

## 3. Limits (Redis sliding windows, keyed `otp:ip:{ip}:{window}`)

| Window | All sends per IP | Sends for UNKNOWN numbers per IP |
|---|---|---|
| 1 minute | 6 | 3 |
| 1 hour | 30 | 8 |
| 24 hours | 80 | 15 |

- Unknown-number sends are the expensive/risky path (SMS to arbitrary numbers) —
  they get the tighter second column.
- On breach: HTTP 429 with the existing trilingual `retry_after_seconds` body
  (reuse `_rate_limit_detail`), plus an `audit_events` row
  (`auth.otp_ip_limited`, ip, phone, window) for forensics.

### NAT caveat (important for this factory)
Factory Wi-Fi puts many workers behind ONE egress IP. Shift start = legitimate
burst. Two mitigations, both env-driven:
- `OTP_IP_ALLOWLIST` — comma-separated CIDRs (factory static egress) exempt from
  per-IP limits (per-phone limits still apply).
- Limits in the table above are deliberately ≥ 3× the worst legitimate burst
  observed (tune after 1 week of measurement — see §5).

## 4. Global circuit breaker (SMS budget protection)

- Counter `otp:global:sms:1h` incremented on every REAL SMS handed to
  SMSGatewayHub. Threshold via env `OTP_GLOBAL_HOURLY_CAP` (suggest 300).
- On breach: (a) unknown-number sends are refused with the friendly
  "registration temporarily closed" 403 (existing message — auto-closes
  registration under attack, existing employees keep logging in), (b) a
  `registration_pending`-style alert notification goes to CGM, (c) audit row.
- Auto-resets each hour; no manual unlock needed.

## 5. Rollout plan

1. Ship in SHADOW mode first (`OTP_IP_LIMIT_MODE=log`): count + audit, never block.
   Run 1 week across a shift cycle to measure real per-IP peaks (factory NAT).
2. Set final numbers from measured p99 × 3, add factory CIDR to allowlist.
3. Flip `OTP_IP_LIMIT_MODE=enforce`.
4. Dashboard: 429/hour and SMS/hour visible in webdash admin (nice-to-have).

## 6. Explicitly out of scope (future options)

- CAPTCHA on repeated unknown-number attempts.
- Device-fingerprint throttling (app attestation / Play Integrity).
- WAF/ingress-level rate limiting (belt-and-braces; app-level is authoritative).
