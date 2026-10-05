// Pure tap → AR-preview coordinate mapping. No React Native imports so it runs
// under `node --test`.
//
// WHY THIS EXISTS (bug found 2026-10-06, v1.0.27 field test):
// the overlay's touch layer deliberately stops short of the shutter controls
// (`bottom: 28%`), so its own height is only ~72% of the AR preview. The old code
// divided locationY by THAT height, while both consumers of the fraction — the
// crosshair (drawn in the full-size overlay) and the native `setTarget` (a
// fraction of the full camera preview) — read it as a fraction of the FULL view.
// Every tap therefore landed ~1/0.72 = 1.39x too low: at 40% of the screen the
// crosshair sat ~15% of the screen height BELOW the finger, and the depth sample
// was taken there too, so the measurement followed the wrong point.
//
// RULE: a tap is always expressed as a fraction of the AR PREVIEW's own measured
// frame. Never the window, never the touch layer's frame, never an assumed inset.

export interface Rect {
  /** x/y are relative to the AR preview frame (React Native onLayout gives a
   * child's offset inside its parent). */
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Size {
  w: number;
  h: number;
}

export function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/**
 * Map a touch reported in `layer`-local coordinates (React Native's
 * `nativeEvent.locationX/locationY`) to a fraction of the AR preview `view`.
 *
 * Returns null when either frame has not been measured yet — the caller must
 * ignore the tap rather than guess, because a guess puts the crosshair (and the
 * depth sample) somewhere the user did not touch.
 */
export function tapToViewFraction(
  localX: number,
  localY: number,
  layer: Rect,
  view: Size,
): { x: number; y: number } | null {
  if (!Number.isFinite(localX) || !Number.isFinite(localY)) return null;
  if (!view || !(view.w > 0) || !(view.h > 0)) return null;
  if (!layer || !(layer.w > 0) || !(layer.h > 0)) return null;
  // touch → absolute position inside the AR preview frame
  const absX = layer.x + localX;
  const absY = layer.y + localY;
  return { x: clamp01(absX / view.w), y: clamp01(absY / view.h) };
}
