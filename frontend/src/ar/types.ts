// Shared types for the on-device AR object-distance feature (PART 1).
// Framework-free so the pure logic can be unit-tested with `node --test`.

export type DistanceMethod =
  | "lidar" // iOS ARKit hardware scene depth (LiDAR)
  | "depth" // Android ARCore Depth API
  | "ar_plane" // raycast / hit-test against a plane or scene geometry
  | "ar_point" // raycast against a depth/feature point (incl. Instant Placement)
  | "feature" // nearest tracked feature points (median)
  | "none"; // no AR available — plain camera, distance not measured

export type DistanceConfidence = "high" | "medium" | "low";

export type TrackingState =
  | "normal"
  | "limited"
  | "initializing"
  | "relocalizing"
  | "notAvailable";

/** Automatic-fix hint surfaced to the user (never a technical message). */
export type DistanceHint =
  | "low_light"
  | "no_texture"
  | "hold_steady"
  | "initializing"
  | "too_close"
  | "too_far"
  | "tracking_lost"
  | null;

export interface DistanceSample {
  value: number; // metres
  timestamp: number; // ms epoch
}

export interface CameraIntrinsics {
  fx: number; // focal length in pixels
  fy: number;
  cx: number; // principal point
  cy: number;
  width: number; // image width the intrinsics refer to
  height: number;
}

/** A throttled (~10 Hz) live update coming from native over the bridge. All
 * fields are treated as untrusted (may be null / missing / string-typed). */
export interface RawArUpdate {
  distanceM?: number | string | null;
  method?: string | null;
  trackingState?: string | null;
  spreadM?: number | string | null;
  sampleCount?: number | string | null;
  hint?: string | null;
  torchOn?: boolean | null;
  targetX?: number | string | null;
  targetY?: number | string | null;
}

/** Result of summarising a rolling window into one displayable reading. */
export interface DistanceReading {
  distanceM: number | null;
  uncertaintyM: number | null;
  method: DistanceMethod;
  confidence: DistanceConfidence;
  trackingState: TrackingState;
  sampleCount: number;
  spread: number;
  approx: boolean; // beyond the tier's reliable range (show greyed "≈")
  show: boolean; // false ⇒ hide the number (never show a guess)
  hint: DistanceHint;
}

/** Everything native records with a still capture — persisted with the photo. */
export interface CaptureDistanceMeta {
  distance_m: number | null;
  distance_uncertainty_m: number | null;
  distance_method: DistanceMethod;
  distance_confidence: DistanceConfidence;
  sample_count: number;
  sample_spread_m: number | null;
  tracking_state: TrackingState;
  tap_x: number; // fraction 0..1 of frame width
  tap_y: number; // fraction 0..1 of frame height
  device_model: string | null;
  torch_auto: boolean;
  tier_switches: number;
  tracking_resets: number;
}

export interface CaptureResult {
  uri: string;
  width: number;
  height: number;
  intrinsics: CameraIntrinsics | null;
  distance: CaptureDistanceMeta;
}

export interface ArCapabilities {
  supported: boolean; // ARKit/ARCore usable on this device
  hasHardwareDepth: boolean; // LiDAR (iOS) / Depth API (Android)
  reason: string; // "ok" | "no_native" | "unsupported_device" | "no_arcore" | ...
}
