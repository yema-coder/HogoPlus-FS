# Google Play — Data Safety questionnaire answers (Hogo Plus FS v1.0.11)

Fill Play Console → App content → Data safety exactly as below. "Shared" in Play's
definition means transfer to a third party for THEIR purposes — our processors (AWS
Rekognition, R2 storage, SMS gateway, Expo push) act on our behalf under the
service-provider exception, so every item below is **Collected = Yes, Shared = No**.

## Overview questions
- Does your app collect or share any of the required user data types? → **Yes**
- Is all of the user data collected by your app encrypted in transit? → **Yes** (HTTPS/TLS only)
- Do you provide a way for users to request that their data is deleted? → **Yes**
  (deletion requests via Time Office / support@hogoplus.in — accounts are employer-managed;
  state this in the free-text if asked)

## Data types

| Play category → type | Collected | Shared | Ephemeral | Required/Optional | Purposes |
|---|---|---|---|---|---|
| Personal info → Name | Yes | No | No | Required | App functionality, Account management |
| Personal info → Phone number | Yes | No | No | Required | App functionality, Account management (OTP login) |
| Personal info → Other info (employee ID, department, role) | Yes | No | No | Required | App functionality, Account management |
| Location → Precise location | Yes | No | No | Required | App functionality (attendance presence verification, incident location tagging) |
| Photos and videos → Photos | Yes | No | No | Required | App functionality (attendance selfies incl. face verification, incident photos) |
| Photos and videos → Videos | Yes | No | No | Optional | App functionality (incident videos) |
| Audio files → Voice or sound recordings | Yes | No | No | Optional | App functionality (incident voice notes) |
| App activity → Other user-generated content | Yes | No | No | Optional | App functionality (incident descriptions, chat with SOP assistant) |
| Device or other IDs → Device or other IDs | Yes | No | No | Required | App functionality (push-notification token) |

Everything else (contacts, calendar, messages, health, financial info, browsing history,
installed apps, email address) → **Not collected**.

Notes for the reviewer-facing free text:
- Face data: punch selfies are compared to a stored reference selfie via AWS Rekognition
  (processor on our behalf) solely to verify attendance identity. Declare selfies under
  **Photos**; Play has no separate biometric category — do NOT tick any extra category.
- No ads, no analytics SDKs, no data sold.
- Data collection is a condition of employment for factory attendance; users cannot opt out
  of required items → mark those **Required**.

## App access (review login) — what to paste in Play Console
> This is an internal workforce app; accounts are provisioned by the employer. A dedicated
> demo account with representative sandbox data is provided for review:
> 1. Open the app, choose any language, enter phone number **+91 9000000500**.
> 2. Tap "Send OTP", then enter the one-time code **<DEMO_OTP you set in .env>**.
> 3. This logs into a Chief General Manager demo account (full feature set: attendance
>    punch, incident reporting, approvals, dashboards). A worker-level demo:
>    **+91 9000000001**, same code.
> The demo account operates on isolated demonstration data only.

## .env lines to enable the review login (add at submission, remove after approval)
On the Mumbai host, edit the backend .env, then `sudo docker compose up -d backend`:

    DEMO_OTP_ENABLED="true"
    DEMO_OTP="<pick a random 6-digit code, e.g. 743912 — do NOT use 123456>"
    DEMO_OTP_WHITELIST=""

Scope (verified in code, `auth.py verify_otp`): the fixed code works ONLY for employee rows
with `is_demo=true` (the isolated demo bubble — D-series showcase accounts, zero real data)
plus any real number explicitly listed in DEMO_OTP_WHITELIST (leave it EMPTY so no real
account is reachable). Real employees always require a real SMS OTP regardless of this flag.
No SMS is ever sent to demo numbers. After Play approval: set `DEMO_OTP_ENABLED="false"`
and `docker compose up -d backend` again.

## Also required by Play before submission
- Privacy policy URL: **https://hogoplus.in/privacy.html** (file: `docs/privacy.html` in this
  repo — upload to the web root; review the two placeholders: contact email
  support@hogoplus.in and effective date).
- App category: Business. Target audience: 18+. Ads: No.
- Permissions declaration: CAMERA, RECORD_AUDIO, ACCESS_FINE_LOCATION, BLUETOOTH_SCAN/CONNECT,
  POST_NOTIFICATIONS — all already declared in the manifest with the in-app runtime flows.
