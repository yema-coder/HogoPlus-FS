import { test } from "node:test";
import assert from "node:assert/strict";

import {
  bool,
  clamp01,
  num,
  parseArUpdate,
  parseCapabilities,
  parseCaptureResult,
  parseIntrinsics,
} from "../parseCaptureResult.ts";

test("num coerces strings, rejects garbage", () => {
  assert.equal(num("6.4"), 6.4);
  assert.equal(num(6.4), 6.4);
  assert.equal(num(null), null);
  assert.equal(num(undefined), null);
  assert.equal(num(""), null);
  assert.equal(num("abc"), null);
  assert.equal(num(NaN), null);
});

test("bool and clamp01", () => {
  assert.equal(bool("true"), true);
  assert.equal(bool(1), true);
  assert.equal(bool(false), false);
  assert.equal(bool(undefined), false);
  assert.equal(clamp01(1.5), 1);
  assert.equal(clamp01(-0.2), 0);
  assert.equal(clamp01("0.3"), 0.3);
  assert.equal(clamp01(null), 0.5); // default centre
});

test("parseIntrinsics requires positive focal length", () => {
  assert.equal(parseIntrinsics(null), null);
  assert.equal(parseIntrinsics({ fx: 0, fy: 0 }), null);
  assert.equal(parseIntrinsics({ fx: "-3", fy: "5" }), null);
  const ok = parseIntrinsics({ fx: "1000", fy: 1000, width: 1920, height: 1080 });
  assert.deepEqual(ok, { fx: 1000, fy: 1000, cx: 960, cy: 540, width: 1920, height: 1080 });
});

test("parseArUpdate never throws on garbage and clamps target", () => {
  const r = parseArUpdate({ distanceM: "6.4", method: "weird", trackingState: null, targetX: "2", targetY: -1, sampleCount: "5" } as never);
  assert.equal(r.distanceM, 6.4);
  assert.equal(r.method, "none"); // unknown method falls back
  assert.equal(r.trackingState, "notAvailable");
  assert.equal(r.targetX, 1); // clamped
  assert.equal(r.targetY, 0); // clamped
  assert.equal(r.sampleCount, 5);
});

test("parseArUpdate handles null/undefined input", () => {
  assert.doesNotThrow(() => parseArUpdate(null));
  assert.doesNotThrow(() => parseArUpdate(undefined));
  const r = parseArUpdate(undefined);
  assert.equal(r.distanceM, null);
  assert.equal(r.method, "none");
});

test("parseCaptureResult: full object", () => {
  const r = parseCaptureResult({
    uri: "file:///x.jpg",
    width: "1920",
    height: 1080,
    deviceModel: "iPhone15,2",
    intrinsics: { fx: 1400, fy: 1400, width: 1920, height: 1080 },
    distance: {
      distanceM: "6.42",
      distanceMethod: "lidar",
      distanceConfidence: "high",
      sampleCount: "12",
      sampleSpreadM: "0.21",
      trackingState: "normal",
      targetX: 0.5,
      targetY: 0.5,
      torchAuto: true,
      tierSwitches: 1,
      trackingResets: 0,
    },
  });
  assert.equal(r.uri, "file:///x.jpg");
  assert.equal(r.width, 1920);
  assert.equal(r.distance.distance_m, 6.42);
  assert.equal(r.distance.distance_method, "lidar");
  assert.equal(r.distance.device_model, "iPhone15,2");
  assert.equal(r.distance.torch_auto, true);
  assert.ok(r.intrinsics && r.intrinsics.cx === 960);
});

test("parseCaptureResult: null/garbage never throws and yields safe defaults", () => {
  assert.doesNotThrow(() => parseCaptureResult(null));
  assert.doesNotThrow(() => parseCaptureResult("nonsense"));
  assert.doesNotThrow(() => parseCaptureResult(42));
  const r = parseCaptureResult(null);
  assert.equal(r.uri, "");
  assert.equal(r.width, 0);
  assert.equal(r.distance.distance_m, null);
  assert.equal(r.distance.distance_method, "none");
  assert.equal(r.distance.distance_confidence, "low");
  assert.equal(r.intrinsics, null);
});

test("parseCaptureResult: missing distance block defaults to none/low", () => {
  const r = parseCaptureResult({ uri: "file:///y.jpg", width: 100, height: 100 });
  assert.equal(r.distance.distance_method, "none");
  assert.equal(r.distance.distance_m, null);
  assert.equal(r.distance.tap_x, 0.5);
});

test("parseCapabilities", () => {
  assert.deepEqual(parseCapabilities({ supported: true, hasHardwareDepth: "true", reason: "ok" }), {
    supported: true,
    hasHardwareDepth: true,
    reason: "ok",
  });
  assert.deepEqual(parseCapabilities(null), { supported: false, hasHardwareDepth: false, reason: "no_native" });
});
