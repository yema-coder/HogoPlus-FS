// Defensive parsers for everything that crosses the native→JS bridge for PART 1.
// ROBUSTNESS RULE 1: the capture→submit flow must never throw. Every value may be
// null, missing, or string-typed — parse with safe fallbacks. Framework-free.

import type {
  ArCapabilities,
  CameraIntrinsics,
  CaptureDistanceMeta,
  CaptureResult,
  DistanceConfidence,
  DistanceHint,
  DistanceMethod,
  RawArUpdate,
  TrackingState,
} from "./types";

const METHODS: DistanceMethod[] = ["lidar", "depth", "ar_plane", "ar_point", "feature", "none"];
const TRACKING: TrackingState[] = ["normal", "limited", "initializing", "relocalizing", "notAvailable"];
const CONF: DistanceConfidence[] = ["high", "medium", "low"];
const HINTS: DistanceHint[] = [
  "low_light",
  "no_texture",
  "hold_steady",
  "initializing",
  "too_close",
  "too_far",
  "tracking_lost",
];

export function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

export function bool(v: unknown): boolean {
  return v === true || v === "true" || v === 1 || v === "1";
}

export function clamp01(v: unknown, fallback = 0.5): number {
  const n = num(v);
  if (n === null) return fallback;
  return Math.min(1, Math.max(0, n));
}

function oneOf<T extends string>(v: unknown, allowed: T[], fallback: T): T {
  return allowed.includes(v as T) ? (v as T) : fallback;
}

export function parseMethod(v: unknown): DistanceMethod {
  return oneOf(v, METHODS, "none");
}
export function parseTracking(v: unknown): TrackingState {
  return oneOf(v, TRACKING, "notAvailable");
}
export function parseConfidence(v: unknown): DistanceConfidence {
  return oneOf(v, CONF, "low");
}
export function parseHint(v: unknown): DistanceHint {
  return v && HINTS.includes(v as Exclude<DistanceHint, null>) ? (v as DistanceHint) : null;
}

export function parseIntrinsics(raw: unknown): CameraIntrinsics | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const fx = num(r.fx);
  const fy = num(r.fy);
  const width = num(r.width);
  const height = num(r.height);
  // focal length is the thing the plate-scale cross-check needs; without fx/fy it's useless
  if (fx === null || fy === null || fx <= 0 || fy <= 0) return null;
  return {
    fx,
    fy,
    cx: num(r.cx) ?? (width ? width / 2 : 0),
    cy: num(r.cy) ?? (height ? height / 2 : 0),
    width: width ?? 0,
    height: height ?? 0,
  };
}

/** Parse a throttled live update. Returns safe primitives for the UI/evaluator. */
export function parseArUpdate(raw: RawArUpdate | null | undefined): {
  distanceM: number | null;
  method: DistanceMethod;
  trackingState: TrackingState;
  spreadM: number | null;
  sampleCount: number;
  hint: DistanceHint;
  torchOn: boolean;
  targetX: number;
  targetY: number;
} {
  const r = (raw ?? {}) as RawArUpdate;
  return {
    distanceM: num(r.distanceM),
    method: parseMethod(r.method),
    trackingState: parseTracking(r.trackingState),
    spreadM: num(r.spreadM),
    sampleCount: Math.max(0, Math.round(num(r.sampleCount) ?? 0)),
    hint: parseHint(r.hint),
    torchOn: bool(r.torchOn),
    targetX: clamp01(r.targetX),
    targetY: clamp01(r.targetY),
  };
}

/** Parse a still-capture result. Guarantees a usable object even for garbage input.
 * `uri` may come back empty — the caller is responsible for treating "" as failure. */
export function parseCaptureResult(raw: unknown): CaptureResult {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const dist = (r.distance && typeof r.distance === "object" ? r.distance : r) as Record<string, unknown>;

  const distanceMeta: CaptureDistanceMeta = {
    distance_m: num(dist.distance_m ?? dist.distanceM),
    distance_uncertainty_m: num(dist.distance_uncertainty_m ?? dist.distanceUncertaintyM),
    distance_method: parseMethod(dist.distance_method ?? dist.distanceMethod),
    distance_confidence: parseConfidence(dist.distance_confidence ?? dist.distanceConfidence),
    sample_count: Math.max(0, Math.round(num(dist.sample_count ?? dist.sampleCount) ?? 0)),
    sample_spread_m: num(dist.sample_spread_m ?? dist.sampleSpreadM),
    tracking_state: parseTracking(dist.tracking_state ?? dist.trackingState),
    tap_x: clamp01(dist.tap_x ?? dist.targetX),
    tap_y: clamp01(dist.tap_y ?? dist.targetY),
    device_model: typeof r.deviceModel === "string" ? r.deviceModel : typeof dist.device_model === "string" ? (dist.device_model as string) : null,
    torch_auto: bool(dist.torch_auto ?? dist.torchAuto),
    tier_switches: Math.max(0, Math.round(num(dist.tier_switches ?? dist.tierSwitches) ?? 0)),
    tracking_resets: Math.max(0, Math.round(num(dist.tracking_resets ?? dist.trackingResets) ?? 0)),
  };

  return {
    uri: typeof r.uri === "string" ? r.uri : "",
    width: Math.max(0, Math.round(num(r.width) ?? 0)),
    height: Math.max(0, Math.round(num(r.height) ?? 0)),
    intrinsics: parseIntrinsics(r.intrinsics),
    distance: distanceMeta,
  };
}

export function parseCapabilities(raw: unknown): ArCapabilities {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  return {
    supported: bool(r.supported),
    hasHardwareDepth: bool(r.hasHardwareDepth),
    reason: typeof r.reason === "string" ? r.reason : "no_native",
  };
}
