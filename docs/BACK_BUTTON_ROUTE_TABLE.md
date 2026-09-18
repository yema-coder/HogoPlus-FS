# Back Button — Full Route Table (v1.0.25)

**One shared header:** every navigable screen renders `src/components/ScreenHeader.tsx`
(back arrow → `router.back()`, falls back to `/(tabs)/home` for orphan deep-links; screens
can pass `backTo`/`onBack` for deterministic flows).

**Android hardware back (app/(tabs)/_layout.tsx):**
- Sub-screen on top → pops back (never exits; orphan deep-link lands on Home)
- Non-Home root tab → goes to Home tab
- Home tab → "Press back again to exit" toast, 2-second window

**Regression guard:** `yarn check:headers` (`frontend/scripts/check-screen-headers.js`)
fails with exit 1 if any non-exempt route file lacks `<ScreenHeader`. Exemptions carry a
written reason inside the script.

Roles: **W** = Worker/Staff/Clerk (incl. Civil, Distillery, all depts) · **M** = Dept/TO/Security Manager · **T** = CGM/MD.

| # | Route | Screen | Roles | Back BEFORE (≤1.0.23) | Back NOW |
|---|-------|--------|-------|------------------------|----------|
| 1 | `/(auth)/language` | Language pick | all (logged out) | n/a — first screen | exempt (first screen) |
| 2 | `/(auth)/phone` | Phone entry | all (logged out) | n/a — auth root | exempt (auth root) |
| 3 | `/(auth)/otp` | OTP entry | all (logged out) | "Change number" link | "Change number" link (kept) |
| 4 | `/(auth)/register-name` | Registration: name | new users | ✗ missing | ✓ ScreenHeader |
| 5 | `/(auth)/register-selfie` | Registration: selfie | new users | ✗ missing | ✓ ScreenHeader |
| 6 | `/(auth)/pending` | Awaiting approval | new users | n/a — logout only | exempt (logout only) |
| 7 | `/permissions` | Permission primer | all (once) | n/a — forward-only gate | exempt (forward-only gate) |
| 8 | `/face-enroll` | Face enrollment | all (once) | ✗ hardware back exited | ✓ ScreenHeader + BackHandler → finish() |
| 9 | `/(tabs)/home` | Home | W M T | hardware back exited app | double-press-to-exit toast |
| 10 | `/(tabs)/department` | Department / My dept | W M T | ✗ missing (stuck) | ✓ ScreenHeader backTo Home |
| 11 | `/(tabs)/reports` | My Complaints / Reports | W M T | ✗ missing (stuck) | ✓ ScreenHeader backTo Home |
| 12 | `/(tabs)/alerts` | Alerts | W M T | ✗ missing (stuck) | ✓ ScreenHeader backTo Home |
| 13 | `/(tabs)/approvals` | Approvals | M T | ✗ missing | ✓ ScreenHeader backTo Home |
| 14 | `/(tabs)/profile` | Profile | W M T | ✗ missing | ✓ ScreenHeader backTo Home |
| 15 | `/attendance/punch` | Punch in/out | W M T | ✗ missing | ✓ ScreenHeader |
| 16 | `/attendance/result` | Punch result | W M T | ✗ missing | ✓ ScreenHeader backTo Home |
| 17 | `/attendance/history` | My attendance | W M T | ✗ missing | ✓ ScreenHeader |
| 18 | `/incident/capture` | Report complaint (camera) | W M T | ✗ missing | ✓ ScreenHeader (both capture+preview) |
| 19 | `/incident/[id]` | Complaint detail | W M T | ✗ missing | ✓ ScreenHeader |
| 20 | `/incident/success` | Complaint submitted | W M T | ✗ missing | ✓ ScreenHeader backTo Home |
| 21 | `/form/[id]` | Dept form fill | W M T | ✗ missing | ✓ ScreenHeader |
| 22 | `/form/success` | Form submitted | W M T | ✗ missing | ✓ ScreenHeader backTo Department |
| 23 | `/submission/[id]` | Submission detail | W M T | ✗ missing | ✓ ScreenHeader |
| 24 | `/swap/new` | Shift swap request | W M T | ✗ missing | ✓ ScreenHeader |
| 25 | `/shift` | My shift | W M T | ✗ missing | ✓ ScreenHeader |
| 26 | `/announce` | Announcements | M T | ✗ missing | ✓ ScreenHeader |
| 27 | `/sahayak` | Sahayak AI assistant | W M T | ✗ missing | ✓ ScreenHeader |
| 28 | `/id-card` | My ID card | W M T | ✗ missing | ✓ ScreenHeader |
| 29 | `/vehicle` | Vehicle register | Security M T | ✗ missing | ✓ ScreenHeader |
| 30 | `/vehicle/new` | New gate entry | Security M T | ✗ missing | ✓ ScreenHeader |
| 31 | `/employees` | Employee directory | TO-M, HO-M, T | ✗ missing | ✓ ScreenHeader |
| 32 | `/employees/new` | Add-employee wizard | TO-M, HO-M, T | ✗ missing | ✓ ScreenHeader onBack=step-back |
| 33 | `/employees/edit` | Edit employee | TO-M, T | ✗ missing | ✓ ScreenHeader |
| 34 | `/ble-diag` | BLE diagnostics | all (debug) | ✗ missing | ✓ ScreenHeader |
| 35 | `/index` | Root redirect | — | n/a (redirect) | exempt (redirect) |
| 36 | `/presence-consent` | Live-tracking consent (v1.0.25) | pilot W | — new | ✓ ScreenHeader onBack=decline |
| 37 | `/battery-help` | OEM battery settings help (v1.0.25) | pilot W | — new | ✓ ScreenHeader |
| 38 | `/delete-account` | Delete my account (v1.0.25) | W M T | — new | ✓ ScreenHeader |

Every "✓ ScreenHeader" row is enforced forever by `yarn check:headers`.
