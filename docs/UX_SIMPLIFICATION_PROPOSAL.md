# UX SIMPLIFICATION PROPOSAL — for approval before any code
User reality: semi-literate rural workers, shift-change hurry, dirty/wet hands, low-end
Androids, Marathi first. Design rule applied throughout: **one glance, one thumb, zero reading.**

## A. Tap counts today → proposed (top 5 actions)

| Action | Taps today | Proposed | How |
|--------|-----------|----------|-----|
| 1. Punch in/out | 3 (open app → Punch tile → confirm on punch screen) | **1–2** | Home "PUNCH" becomes a full-width thumb bar that starts BLE scan immediately on tap; auto-submits when zone+face pass. Confirm step only when something is abnormal. |
| 2. Report incident | 5 (home → report tile → category pick → photo → submit) | **3** | Camera-first: tile opens straight into camera; category chips appear ON the photo preview (AI pre-selects, worker just confirms); submit = one big bar. |
| 3. Vehicle entry (security) | 6 (home → vehicle → new → direction → plate+fields → save) | **3–4** | "IN"/"OUT" as two giant buttons on the vehicle widget itself; ANPR fills the plate; purpose = 4 chips (cane/material/staff/visitor); driver name optional behind "More". |
| 4. Fill a form | 4 + typing | 3 + minimal typing | Remember-last-values per form per user (90% of gauge readings repeat); voice-fill button already exists — surface it at the top, not bottom. |
| 5. Approvals (manager) | 4 per item | **2** | Swipe right = approve, swipe left = reject on each card (with undo toast) — v1.0.20's evidence card makes the decision instant; modal only for editing emp-id/dept. |

## B. Hide/remove for Worker role (⚠️ = removes a capability, your call)
1. Hide "Reports" tab for rank-5 workers — they never open aggregate reports. Their history
   lives under Profile → My attendance. (⚠️ hides, not deletes: role-gated)
2. Collapse home to max 4 tiles for workers: Punch, Report, My shift, Sahayak. Everything
   else behind a "More" tile. (config-driven — home_configs already supports this, zero schema work)
3. ID-card, language switch, diagnostics → stay under Profile only.
4. ⚠️ Remove shift-swap entry point for non-eligible workers entirely (today it shows then
   errors). Capability unchanged for eligible ones.

## C. Replace typing (biggest win for dirty hands)
1. Incident description: **default to voice note**, typing is the fallback (flip current order).
2. Vehicle purpose/driver: chips + last-10-drivers pick list; no free text unless "Other".
3. Forms: numeric keypads for all number fields (already), plus per-field "same as last time" ghost value tap.
4. Approve modal: suggested emp-id pre-filled (done in v1.0.20), dept pre-filled from the
   registrant's request — approving becomes tap-tap.

## D. Visual/state changes
1. Punch state colours: big green "आत आहात" / grey "बाहेर" banner on home (state, not text).
2. All primary buttons ≥56 dp; chips ≥44 dp (mostly true — enforce on vehicle chips + form chips).
3. Marathi labels first everywhere (already default); shorten the 6 longest Marathi strings
   (announce, swap explainers) to ≤6 words.
4. Kill paragraph screens: the two offenders are the self-reg "pending approval" explainer and
   the swap-request explainer → replace with icon + one line + illustration.

## E. Explicitly NOT proposing
- No re-navigation/new tab structure — muscle memory of 400 field users beats theory.
- No gesture-only actions without a visible button twin (gloves + cheap digitisers misread swipes).

**Awaiting your approval per line item (A1–A5, B1–B4, C1–C4, D1–D4). Nothing here is built yet.**
