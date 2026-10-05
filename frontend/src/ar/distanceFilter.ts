// Pure, framework-free distance math for PART 1 (sampling, outlier rejection,
// median, uncertainty, tier/confidence selection). No React Native imports so
// it runs under `node --test`. Never throws; blank/hidden is correct when unsure.

import type {
  DistanceConfidence,
  DistanceHint,
  DistanceMethod,
  DistanceReading,
  DistanceSample,
  TrackingState,
} from "./types";

// ---- basic statistics ----

export function median(xs: number[]): number {
  const s = xs.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (s.length === 0) return NaN;
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** Median Absolute Deviation. */
export function mad(xs: number[], med?: number): number {
  const vals = xs.filter((x) => Number.isFinite(x));
  if (vals.length === 0) return NaN;
  const m = med ?? median(vals);
  return median(vals.map((x) => Math.abs(x - m)));
}

export function stdev(xs: number[]): number {
  const vals = xs.filter((x) => Number.isFinite(x));
  if (vals.length < 2) return 0;
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const variance = vals.reduce((a, b) => a + (b - mean) ** 2, 0) / (vals.length - 1);
  return Math.sqrt(variance);
}

/** Reject outliers using MAD (robust). Degenerate spread ⇒ keep everything. */
export function rejectOutliers(xs: number[], k = 3): number[] {
  const vals = xs.filter((x) => Number.isFinite(x));
  if (vals.length <= 2) return vals;
  const m = median(vals);
  const md = mad(vals, m);
  if (!Number.isFinite(md) || md === 0) return vals;
  const scaled = 1.4826 * md; // MAD → σ estimate for a normal distribution
  const kept = vals.filter((x) => Math.abs(x - m) <= k * scaled);
  return kept.length ? kept : vals;
}

/** Keep only samples inside the rolling window (default ~400 ms). */
export function pruneWindow(
  samples: DistanceSample[],
  now: number,
  windowMs = 400,
): DistanceSample[] {
  return samples.filter((s) => Number.isFinite(s.value) && now - s.timestamp <= windowMs);
}

// ---- tier ranges (honest working range per 1.3; no accuracy claims in UI) ----

interface TierRange {
  min: number; // below this ⇒ "too close"
  reliable: number; // trustworthy up to here
  hardMax: number; // beyond this ⇒ hide (never guess)
}

export const TIER_RANGE: Record<DistanceMethod, TierRange> = {
  lidar: { min: 0.1, reliable: 5, hardMax: 8 },
  depth: { min: 0.3, reliable: 5, hardMax: 8 },
  ar_plane: { min: 0.3, reliable: 15, hardMax: 30 },
  ar_point: { min: 0.3, reliable: 10, hardMax: 20 },
  feature: { min: 0.3, reliable: 8, hardMax: 15 },
  none: { min: 0, reliable: 0, hardMax: 0 },
};

const HIGH_SPREAD_HW = 0.25; // metres — hardware depth stable band
const HIGH_SPREAD_PLANE = 0.15;
const MEDIUM_SPREAD = 0.4;

// ---- convergence gate (field fix, 2026-10-06) --------------------------------
// A number must never appear off one lucky frame. Before anything is rendered the
// window must hold at least MIN_SAMPLES readings AND they must agree: a single
// sample has a mathematical spread of 0, which used to sail straight through the
// confidence check and print a confident-looking wrong distance.

/** Minimum readings inside the rolling window before any number may be shown. */
export const MIN_SAMPLES = 3;
/** Absolute floor for the allowed spread (metres) — depth noise at close range. */
export const SPREAD_FLOOR_M = 0.1;
/** Allowed spread as a fraction of the measured distance, per tier family. */
export const SPREAD_REL_HW = 0.08; // lidar / depth
export const SPREAD_REL_AR = 0.12; // ar_plane / ar_point / feature

/** Largest spread (metres) we will still call converged at this distance. */
export function spreadLimit(method: DistanceMethod, distanceM: number): number {
  if (!Number.isFinite(distanceM) || distanceM <= 0) return SPREAD_FLOOR_M;
  const rel = method === "lidar" || method === "depth" ? SPREAD_REL_HW : SPREAD_REL_AR;
  return Math.max(SPREAD_FLOOR_M, rel * distanceM);
}

export function pickConfidence(
  method: DistanceMethod,
  spread: number,
  tracking: TrackingState,
  count: number,
): DistanceConfidence {
  if (method === "none" || count === 0) return "low";
  if (tracking === "notAvailable" || tracking === "initializing" || tracking === "relocalizing") {
    return "low";
  }
  const hw = method === "lidar" || method === "depth";
  if (hw && tracking === "normal" && spread <= HIGH_SPREAD_HW) return "high";
  if (method === "ar_plane" && tracking === "normal" && spread <= HIGH_SPREAD_PLANE) return "high";
  if (
    (method === "ar_plane" || method === "ar_point" || method === "feature") &&
    spread <= MEDIUM_SPREAD &&
    (tracking === "normal" || tracking === "limited")
  ) {
    return "medium";
  }
  return "low";
}

export interface EvaluateInput {
  samples: DistanceSample[];
  now: number;
  method: DistanceMethod;
  trackingState: TrackingState;
  windowMs?: number;
  hint?: DistanceHint;
}

/** Summarise a rolling window into one displayable reading, applying every
 * accuracy rule from 1.3. Returns show=false whenever we must not show a guess. */
export function evaluateDistance(input: EvaluateInput): DistanceReading {
  const { now, method, trackingState, windowMs = 400 } = input;
  const windowed = pruneWindow(input.samples ?? [], now, windowMs);
  const values = windowed.map((s) => s.value);
  const filtered = rejectOutliers(values);
  const count = filtered.length;
  const med = count ? median(filtered) : NaN;
  // Prefer sample stdev; fall back to a MAD-derived σ for tiny samples.
  const spread = count >= 2 ? stdev(filtered) : count ? 1.4826 * mad(filtered) : Infinity;
  const confidence = pickConfidence(method, spread, trackingState, count);

  const range = TIER_RANGE[method] ?? TIER_RANGE.none;
  const hasValue = Number.isFinite(med) && method !== "none";
  const tooClose = hasValue && med < range.min;
  const tooFar = hasValue && med > range.hardMax;
  const approx = hasValue && med > range.reliable && med <= range.hardMax;

  // Convergence: enough samples AND close enough agreement. Without this a single
  // sample (spread 0 by definition) printed a confident number — the field bug
  // where a 2 m object read 6.4 m and jumped around.
  const converged =
    hasValue && count >= MIN_SAMPLES && Number.isFinite(spread) && spread <= spreadLimit(method, med);

  let hint: DistanceHint = input.hint ?? null;
  if (!hint) {
    if (trackingState === "initializing") hint = "initializing";
    else if (trackingState === "relocalizing" || trackingState === "notAvailable") hint = "tracking_lost";
    else if (tooClose) hint = "too_close";
    else if (tooFar) hint = "too_far";
    else if (hasValue && count < MIN_SAMPLES) hint = "converging";
    else if (hasValue && !converged) hint = "unstable";
  }

  const show = hasValue && converged && confidence !== "low" && !tooClose && !tooFar;

  return {
    distanceM: hasValue ? round2(med) : null,
    uncertaintyM: hasValue && Number.isFinite(spread) ? round2(spread) : null,
    method,
    confidence,
    trackingState,
    sampleCount: count,
    spread: Number.isFinite(spread) ? round2(spread) : 0,
    approx,
    show,
    converged,
    hint,
  };
}

export function round2(x: number): number {
  return Math.round(x * 100) / 100;
}

/** Does a CAPTURED measurement clear the same bar as the live display?
 *
 * The native layer resolves a capture from whatever its rolling window holds —
 * including a single sample — so without this check an unconverged distance is
 * persisted on the incident and shown to a manager in the dashboard, even while
 * the camera UI correctly showed nothing. Same rule, one place. */
export function captureMeetsBar(meta: {
  distance_m?: number | null;
  distance_method?: DistanceMethod | string | null;
  distance_confidence?: DistanceConfidence | string | null;
  sample_count?: number | null;
  sample_spread_m?: number | null;
} | null): boolean {
  if (!meta) return false;
  const d = meta.distance_m;
  const method = (meta.distance_method ?? "none") as DistanceMethod;
  if (d == null || !Number.isFinite(d) || method === "none") return false;
  if (meta.distance_confidence === "low") return false;
  const count = meta.sample_count ?? 0;
  if (count < MIN_SAMPLES) return false;
  const spread = meta.sample_spread_m;
  if (spread != null && Number.isFinite(spread) && spread > spreadLimit(method, d)) return false;
  const range = TIER_RANGE[method] ?? TIER_RANGE.none;
  return d >= range.min && d <= range.hardMax;
}

/** Display string: "6.4 m ±0.3", greyed "≈ 12.1 m" when approx, "" when hidden. */
export function formatDistance(r: DistanceReading): string {
  if (!r.show || r.distanceM == null) return "";
  const base = `${r.distanceM.toFixed(1)} m`;
  // ± is shown whenever the spread is meaningful — including on an approximate
  // reading, where honesty about the margin matters most.
  const pm = r.uncertaintyM != null && r.uncertaintyM >= 0.1 ? ` ±${r.uncertaintyM.toFixed(1)}` : "";
  return r.approx ? `≈ ${base}${pm}` : `${base}${pm}`;
}
