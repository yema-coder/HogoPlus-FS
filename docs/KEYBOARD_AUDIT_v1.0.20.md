# KEYBOARD AUDIT — v1.0.20 (exhaustive input-surface enumeration)

## How this audit was done — and its honest limits
Every screen/modal/sheet containing a text input was enumerated from the code and its
keyboard handling inspected line-by-line. **RNKC (react-native-keyboard-controller) is a
native module — it does nothing on web, which is exactly why the previous web sweep gave a
false pass.** From this sandbox I cannot drive a physical Android phone, so the table below
is a *code-level* audit: every surface verified to use the RNKC primitives with the correct
props. The four acceptance criteria per screen (field visible, submit reachable, tap-outside
dismiss, scroll-with-keyboard) must be **spot-checked by you on the factory phones** — column
"Device check" is intentionally left for your tick. The v1.0.19 build already carries all of
this code; no regressions were found and no gaps remained.

Acceptance criteria key: **V**=focused field visible above keyboard · **S**=submit reachable
with keyboard open · **D**=tap-outside dismisses · **Sc**=scrolls with keyboard up.

| # | Surface | Inputs | Handling (code) | V | S | D | Sc | Notes / what changed | Device check |
|---|---------|--------|-----------------|---|---|---|----|----------------------|--------------|
| 1 | (auth)/phone | phone number | RNKC `KeyboardAwareScrollView` + sticky CTA | ✅ | ✅ | ✅ | ✅ | fixed in v1.0.18 migration | ☐ |
| 2 | (auth)/otp | 6-digit OTP | RNKC `KeyboardAwareScrollView`; auto-submit on 6th digit | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 3 | (auth)/register-name | full name | RNKC `KeyboardAwareScrollView` | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 4 | (tabs)/approvals — reject-reason modal | reason text | RNKC `KeyboardAvoidingView` inside `Modal` | ✅ | ✅ | ✅ | ✅ | RNKC KAV (not RN KAV) — survives nested Modal on Android | ☐ |
| 5 | (tabs)/approvals — approve modal | emp_id + dept | RNKC `KeyboardAvoidingView` | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 6 | announce | title + body (multiline) | RNKC `KeyboardAwareScrollView` | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 7 | sahayak (AI chat) | chat input | RNKC `KeyboardAvoidingView` + sticky input bar | ✅ | ✅ | ✅ | ✅ | input pinned above keyboard | ☐ |
| 8 | incident/capture | description, voice note fallback | RNKC `KeyboardAwareScrollView` | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 9 | incident/[id] — status note | note input | RNKC `KeyboardAvoidingView` | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 10 | submission/[id] — review note | note | RNKC `KeyboardAvoidingView` | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 11 | swap/new | reason | RNKC `KeyboardAwareScrollView` | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 12 | vehicle/new | plate, driver, purpose… | RNKC `KeyboardAwareScrollView` + `AnprTextInput` | ✅ | ✅ | ✅ | ✅ | built Wave-1 with RNKC from day one | ☐ |
| 13 | employees/new + edit (EmployeeForm) | 8+ fields | RNKC `KeyboardAwareScrollView` (`bottomOffset`) | ✅ | ✅ | ✅ | ✅ | longest form in app — verify last field on small screens | ☐ |
| 14 | employees/index | search box | top-anchored input + `keyboardShouldPersistTaps` + dismiss-on-drag on the list | ✅ | n/a | ✅ | ✅ | input is at the very top — keyboard physically cannot cover it | ☐ |
| 15 | form/[id] (FormRenderer: text/number/date/GPS/photo/voice/ANPR/select fields) | dynamic | RNKC `KeyboardAwareScrollView` wrapping all field types | ✅ | ✅ | ✅ | ✅ | selects/chips open native sheets (no keyboard) | ☐ |
| 16 | EscalateModal | reason | RNKC `KeyboardAvoidingView` inside Modal | ✅ | ✅ | ✅ | ✅ | v1.0.18 | ☐ |
| 17 | ble-diag | none (buttons only) | n/a | – | – | – | – | no inputs | – |

## Gaps found in this audit: **none in code.**
All 16 input surfaces already sit on RNKC primitives; zero screens still import the old
React-Native `KeyboardAvoidingView`. `KeyboardProvider` wraps the app root in `_layout.tsx`.

## Devanagari note (your point about taller glyphs)
All inputs use the Baloo2 font with explicit `minHeight` and no fixed `height` — Devanagari
matras render without clipping in code review. Screens 6 (announce body) and 13 (EmployeeForm)
are the two worth checking in Marathi on the smallest phone you have.

## What to spot-check on factory phones (5 minutes)
1. EmployeeForm (13) — focus the LAST field, keyboard open, small phone, Marathi.
2. Approve modal (5) — emp-id field + Approve button both visible with keyboard open.
3. Sahayak (7) — chat bar rides on top of the keyboard while scrolled mid-history.
4. Vehicle new (12) — plate field with ANPR chip row, keyboard open.
If any fail on device, note screen + phone model; that becomes a targeted RNKC prop fix
(`bottomOffset`/`extraKeyboardSpace`), not another migration.
