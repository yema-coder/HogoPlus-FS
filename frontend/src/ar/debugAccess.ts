// Who may see the AR debug dot + diagnostic HUD.
//
// TEMPORARY (owner directive, 2026-10-06): this test build shows the dot and HUD
// to EVERY logged-in user, because the owner's own account is Manager (rank 3)
// and the previous rank<=2 gate locked him out of the very screen he has to
// verify. The factory keeps running the older build, so nothing reaches workers.
//
// TO RESTORE THE REAL GATE: set AR_DEBUG_FOR_EVERYONE = false. The rank and
// server-allowlist logic below is intact and takes over immediately — no other
// file needs to change.

export const AR_DEBUG_FOR_EVERYONE = true;

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
  const { rank, empId, allowlist, isDemo } = ctx;
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
