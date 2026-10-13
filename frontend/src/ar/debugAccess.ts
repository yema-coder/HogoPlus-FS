// Who may see the AR debug dot + diagnostic HUD.
//
// 2026-10-06: temporarily opened to EVERY logged-in user so the owner (rank 3)
// could verify the AR screens on his own account.
// 2026-10-13: CLOSED again. AR distance is being removed from the app, so this
// now gates only the gallery test-upload button — and the factory is about to
// launch, where no worker should see a test tool. The real gate is back on:
// dev build, demo bubble, rank <= 2, or the server-driven allowlist
// (settings.ar_debug_emp_ids -> profile.ar_debug), which already carries the
// owner's 0001. Flip this constant to true to reopen it for a test build.

export const AR_DEBUG_FOR_EVERYONE = false;

/** Rank at or above which the HUD is normally visible (1 = MD, 2 = CGM). */
export const AR_DEBUG_MIN_RANK = 2;

export interface ArDebugContext {
  /** role rank from the profile (1 = MD … 6 = Worker); undefined = unknown */
  rank?: number | null;
  /** employee id, matched against the server-driven allowlist */
  empId?: string | null;
  /** emp_ids the server says may use AR debug (settings.ar_debug_emp_ids) */
  allowlist?: string[] | null;
  /** account lives in the sealed demo bubble — real workers never match */
  isDemo?: boolean | null;
  /** the SERVER already decided this account is allowlisted
   * (settings.ar_debug_emp_ids -> profile.ar_debug); needs a backend deploy */
  serverAllowed?: boolean | null;
}

function isDev(): boolean {
  // __DEV__ exists in React Native but not under `node --test`.
  return typeof __DEV__ !== "undefined" && __DEV__ === true;
}

/** Pure decision, so both the temporary "everyone" mode and the real gate are
 * unit-testable without a React Native runtime. */
export function evaluateArDebug(
  ctx: ArDebugContext,
  forEveryone: boolean,
  dev: boolean,
): boolean {
  if (forEveryone) return true;
  if (dev) return true;
  const { rank, empId, allowlist, isDemo, serverAllowed } = ctx;
  if (serverAllowed) return true; // server-side allowlist (no app rebuild needed)
  if (isDemo) return true; // demo bubble: any rank, real workers never match
  if (empId && allowlist?.length) {
    const wanted = empId.trim().toUpperCase();
    if (allowlist.some((id) => String(id).trim().toUpperCase() === wanted)) return true;
  }
  return typeof rank === "number" && rank <= AR_DEBUG_MIN_RANK;
}

export function isArDebugEnabled(ctx: ArDebugContext = {}): boolean {
  return evaluateArDebug(ctx, AR_DEBUG_FOR_EVERYONE, isDev());
}
