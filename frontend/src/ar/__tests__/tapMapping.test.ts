import { test } from "node:test";
import assert from "node:assert/strict";

import { clamp01, tapToViewFraction } from "../tapMapping.ts";
import type { Rect } from "../tapMapping.ts";

// Realistic device: Pixel 7 in dp — 412 x 915. The AR preview fills the screen;
// the touch layer stops 28% above the bottom so the shutter stays tappable.
const VIEW = { w: 412, h: 915 };
const TAP_LAYER: Rect = { x: 0, y: 0, w: 412, h: 915 * 0.72 }; // 658.8

test("REGRESSION: the fraction is of the PREVIEW, not of the shorter touch layer", () => {
  // Finger at 300 dp down the screen.
  const got = tapToViewFraction(200, 300, TAP_LAYER, VIEW)!;
  assert.ok(Math.abs(got.y - 300 / 915) < 1e-9, "y must be measured against the preview height");

  // What the old code did: locationY / tapLayer.h — the bug that shipped.
  const buggy = 300 / TAP_LAYER.h;
  assert.ok(buggy > got.y);
  // It placed the crosshair 1/0.72 = 1.39x too low: ~135 dp (≈2 cm) below the
  // finger at this tap position. That is the "+ appears far below my finger".
  const driftDp = (buggy - got.y) * VIEW.h;
  assert.ok(driftDp > 100 && driftDp < 150, `drift should be ~117 dp, got ${driftDp}`);
});

test("x is unaffected (the touch layer spans the full width)", () => {
  const got = tapToViewFraction(206, 100, TAP_LAYER, VIEW)!;
  assert.ok(Math.abs(got.x - 0.5) < 1e-9);
});

test("a touch layer offset INSIDE the preview is added back (header/safe-area case)", () => {
  // If a future layout insets the touch layer below a 48 dp status bar + 64 dp
  // header, locationY is relative to that layer and must be shifted by its origin.
  const inset: Rect = { x: 0, y: 112, w: 412, h: 600 };
  const got = tapToViewFraction(0, 188, inset, VIEW)!;
  assert.ok(Math.abs(got.y - 300 / 915) < 1e-9, "112 + 188 = 300 dp down the preview");
});

test("the preview frame is the reference even when it is NOT the window", () => {
  // AR preview occupying only part of the screen (e.g. 412x600 card inside a
  // 412x915 window). Window dimensions must never enter the calculation.
  const smallView = { w: 412, h: 600 };
  const layer: Rect = { x: 0, y: 0, w: 412, h: 600 * 0.72 };
  const got = tapToViewFraction(206, 300, layer, smallView)!;
  assert.ok(Math.abs(got.y - 0.5) < 1e-9);
  assert.ok(Math.abs(got.x - 0.5) < 1e-9);
});

test("fractions are orientation independent (landscape-shaped preview)", () => {
  const landscape = { w: 915, h: 412 };
  const layer: Rect = { x: 0, y: 0, w: 915, h: 412 };
  const got = tapToViewFraction(457.5, 206, layer, landscape)!;
  assert.ok(Math.abs(got.x - 0.5) < 1e-9);
  assert.ok(Math.abs(got.y - 0.5) < 1e-9);
  // The native layer (ARCore transformCoordinates2d / ARKit displayTransform)
  // consumes exactly this 0..1-of-the-view contract and applies rotation and the
  // aspect-fill crop itself, so JS must never pre-compensate for either.
});

test("corners map to the corners of the preview", () => {
  const tl = tapToViewFraction(0, 0, TAP_LAYER, VIEW)!;
  assert.deepEqual(tl, { x: 0, y: 0 });
  const br = tapToViewFraction(412, 915, TAP_LAYER, VIEW)!;
  assert.deepEqual(br, { x: 1, y: 1 }); // clamped, never beyond the preview
});

test("unmeasured frames return null instead of guessing", () => {
  assert.equal(tapToViewFraction(10, 10, TAP_LAYER, { w: 0, h: 0 }), null);
  assert.equal(tapToViewFraction(10, 10, { x: 0, y: 0, w: 0, h: 0 }, VIEW), null);
  assert.equal(tapToViewFraction(NaN, 10, TAP_LAYER, VIEW), null);
  assert.equal(tapToViewFraction(10, Number.POSITIVE_INFINITY, TAP_LAYER, VIEW), null);
});

test("clamp01 keeps everything inside the preview", () => {
  assert.equal(clamp01(-0.4), 0);
  assert.equal(clamp01(1.7), 1);
  assert.equal(clamp01(0.42), 0.42);
  assert.equal(clamp01(NaN), 0);
});
