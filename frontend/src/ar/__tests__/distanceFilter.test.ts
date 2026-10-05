import { test } from "node:test";
import assert from "node:assert/strict";

import {
  captureMeetsBar,
  evaluateDistance,
  formatDistance,
  MIN_SAMPLES,
  spreadLimit,
  mad,
  median,
  pickConfidence,
  pruneWindow,
  rejectOutliers,
  round2,
  stdev,
} from "../distanceFilter.ts";
import type { DistanceSample } from "../types.ts";

const samples = (vals: number[], now = 1000, step = 30): DistanceSample[] =>
  vals.map((value, i) => ({ value, timestamp: now - (vals.length - 1 - i) * step }));

test("median: odd and even", () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 3, 2]), 2.5);
  assert.ok(Number.isNaN(median([])));
});

test("mad is robust to a single large outlier", () => {
  assert.equal(mad([2, 2, 2, 2]), 0);
  assert.ok(mad([2, 2, 2, 100]) < 1);
});

test("rejectOutliers drops a spike but keeps the cluster", () => {
  const out = rejectOutliers([6.3, 6.4, 6.35, 6.45, 20.0]);
  assert.ok(!out.includes(20.0), "spike removed");
  assert.equal(out.length, 4);
});

test("rejectOutliers keeps everything when spread is degenerate", () => {
  assert.deepEqual(rejectOutliers([5, 5, 5]), [5, 5, 5]);
  assert.deepEqual(rejectOutliers([5]), [5]);
});

test("pruneWindow keeps only recent samples", () => {
  const s = samples([1, 2, 3, 4, 5], 1000, 150); // timestamps 400,550,700,850,1000
  const kept = pruneWindow(s, 1000, 400);
  assert.deepEqual(kept.map((x) => x.value), [3, 4, 5]); // ts<600 dropped
});

test("stdev basic", () => {
  assert.equal(round2(stdev([2, 4, 4, 4, 5, 5, 7, 9])), 2.14);
  assert.equal(stdev([5]), 0);
});

test("pickConfidence: hardware depth stable → high", () => {
  assert.equal(pickConfidence("lidar", 0.1, "normal", 10), "high");
  assert.equal(pickConfidence("depth", 0.2, "normal", 8), "high");
});

test("pickConfidence: feature/limited → medium, high spread → low", () => {
  assert.equal(pickConfidence("feature", 0.3, "limited", 5), "medium");
  assert.equal(pickConfidence("ar_point", 0.9, "normal", 5), "low");
  assert.equal(pickConfidence("none", 0, "normal", 0), "low");
  assert.equal(pickConfidence("lidar", 0.1, "initializing", 5), "low");
});

test("evaluateDistance: stable LiDAR cluster is shown with low uncertainty", () => {
  const r = evaluateDistance({
    samples: samples([2.3, 2.4, 2.35, 2.45, 2.4]),
    now: 1000,
    method: "lidar",
    trackingState: "normal",
  });
  assert.equal(r.show, true);
  assert.equal(r.confidence, "high");
  assert.ok(r.distanceM! >= 2.3 && r.distanceM! <= 2.5);
  assert.equal(r.approx, false); // within LiDAR's 5m reliable range
});

test("evaluateDistance: a spike does not move the reported median", () => {
  const r = evaluateDistance({
    samples: samples([6.3, 6.4, 6.35, 6.45, 25.0]),
    now: 1000,
    method: "lidar",
    trackingState: "normal",
  });
  assert.ok(r.distanceM! < 7, "outlier rejected from median");
});

test("evaluateDistance: high spread → hidden (never a guess)", () => {
  const r = evaluateDistance({
    samples: samples([3, 9, 4, 11, 6]),
    now: 1000,
    method: "feature",
    trackingState: "normal",
  });
  assert.equal(r.show, false);
  assert.equal(r.confidence, "low");
});

test("evaluateDistance: beyond reliable range → approx, hidden beyond hardMax", () => {
  const approx = evaluateDistance({
    samples: samples([6.0, 6.05, 6.02, 6.03]),
    now: 1000,
    method: "lidar", // reliable 5m, hardMax 8m
    trackingState: "normal",
  });
  assert.equal(approx.approx, true);
  assert.equal(approx.show, true);

  const tooFar = evaluateDistance({
    samples: samples([12, 12.1, 12.05]),
    now: 1000,
    method: "lidar",
    trackingState: "normal",
  });
  assert.equal(tooFar.show, false);
  assert.equal(tooFar.hint, "too_far");
});

test("evaluateDistance: method none never shows", () => {
  const r = evaluateDistance({ samples: [], now: 1000, method: "none", trackingState: "notAvailable" });
  assert.equal(r.show, false);
  assert.equal(r.distanceM, null);
});

test("formatDistance strings", () => {
  assert.equal(
    formatDistance({ distanceM: 6.4, uncertaintyM: 0.3, method: "lidar", confidence: "high", trackingState: "normal", sampleCount: 5, spread: 0.3, approx: false, show: true, converged: true, hint: null }),
    "6.4 m ±0.3",
  );
  assert.equal(
    formatDistance({ distanceM: 12.1, uncertaintyM: 0.4, method: "ar_plane", confidence: "medium", trackingState: "normal", sampleCount: 5, spread: 0.4, approx: true, show: true, converged: true, hint: null }),
    "≈ 12.1 m ±0.4",
  );
  assert.equal(
    formatDistance({ distanceM: null, uncertaintyM: null, method: "none", confidence: "low", trackingState: "notAvailable", sampleCount: 0, spread: 0, approx: false, show: false, converged: false, hint: null }),
    "",
  );
});

// ---- convergence gate (field fix 2026-10-06) --------------------------------
// A worker reporting a hazard must never be shown 6.4 m for something 2 m away.
// A blank is correct; a confident wrong number is not.

test("evaluateDistance: ONE sample never shows a number (spread of 1 is a lie)", () => {
  const r = evaluateDistance({
    samples: samples([6.4]),
    now: 1000,
    method: "depth",
    trackingState: "normal",
  });
  assert.equal(r.sampleCount, 1);
  assert.equal(r.spread, 0); // mathematically zero — this is exactly the trap
  assert.equal(r.converged, false);
  assert.equal(r.show, false);
  assert.equal(r.hint, "converging");
  assert.equal(formatDistance(r), "");
});

test("evaluateDistance: below MIN_SAMPLES stays hidden, at MIN_SAMPLES it shows", () => {
  const below = evaluateDistance({
    samples: samples(new Array(MIN_SAMPLES - 1).fill(2.0)),
    now: 1000,
    method: "depth",
    trackingState: "normal",
  });
  assert.equal(below.show, false);
  assert.equal(below.hint, "converging");

  const at = evaluateDistance({
    samples: samples(new Array(MIN_SAMPLES).fill(2.0)),
    now: 1000,
    method: "depth",
    trackingState: "normal",
  });
  assert.equal(at.converged, true);
  assert.equal(at.show, true);
  assert.equal(at.distanceM, 2);
});

test("evaluateDistance: samples that disagree are hidden with the unstable hint", () => {
  // 2.0 / 2.6 / 3.2 around a 2.6 m median: stdev 0.6 > limit max(0.1, 0.08*2.6)=0.21
  const r = evaluateDistance({
    samples: samples([2.0, 2.6, 3.2]),
    now: 1000,
    method: "depth",
    trackingState: "normal",
  });
  assert.equal(r.sampleCount, 3);
  assert.ok(r.spread > spreadLimit("depth", 2.6));
  assert.equal(r.converged, false);
  assert.equal(r.show, false);
  assert.equal(r.hint, "unstable");
  assert.equal(formatDistance(r), "");
});

test("spreadLimit: relative band with an absolute floor, looser for AR tiers", () => {
  assert.equal(spreadLimit("depth", 1), 0.1); // floor wins at close range
  assert.ok(Math.abs(spreadLimit("depth", 5) - 0.4) < 1e-9); // 8% of 5 m
  assert.ok(Math.abs(spreadLimit("ar_plane", 5) - 0.6) < 1e-9); // 12% of 5 m
  assert.equal(spreadLimit("depth", 0), 0.1);
  assert.equal(spreadLimit("depth", NaN), 0.1);
});

test("evaluateDistance: tracking lost hides the number and keeps the hint", () => {
  const r = evaluateDistance({
    samples: samples([2.0, 2.01, 2.02, 2.0]),
    now: 1000,
    method: "depth",
    trackingState: "relocalizing",
  });
  assert.equal(r.show, false);
  assert.equal(r.hint, "tracking_lost");
  assert.equal(formatDistance(r), "");
});

test("formatDistance: an approximate reading still carries its ± margin", () => {
  // ar_plane: reliable to 15 m, hard max 30 m → ~20 m is shown but flagged approx.
  // Spread 0.2 m is inside the 12% band at that distance, so it still converges.
  const r = evaluateDistance({
    samples: samples([20.0, 20.2, 20.1, 20.4, 19.9]),
    now: 1000,
    method: "ar_plane",
    trackingState: "normal",
  });
  assert.equal(r.converged, true);
  assert.equal(r.show, true);
  assert.equal(r.approx, true);
  assert.match(formatDistance(r), /^≈ 20\.1 m ±0\.\d$/);
});

// ---- captured measurement must clear the same bar as the live display -------

test("captureMeetsBar: a one-sample capture is rejected", () => {
  assert.equal(
    captureMeetsBar({
      distance_m: 6.4, distance_method: "depth", distance_confidence: "high",
      sample_count: 1, sample_spread_m: 0,
    }),
    false,
  );
});

test("captureMeetsBar: a converged capture is accepted", () => {
  assert.equal(
    captureMeetsBar({
      distance_m: 2.4, distance_method: "depth", distance_confidence: "high",
      sample_count: 8, sample_spread_m: 0.05,
    }),
    true,
  );
});

test("captureMeetsBar: rejects wide spread, low confidence, no method, out of range", () => {
  const base = { distance_m: 2.4, distance_method: "depth", distance_confidence: "high", sample_count: 8 };
  assert.equal(captureMeetsBar({ ...base, sample_spread_m: 1.2 }), false); // > 8% of 2.4 m
  assert.equal(captureMeetsBar({ ...base, sample_spread_m: 0.05, distance_confidence: "low" }), false);
  assert.equal(captureMeetsBar({ ...base, sample_spread_m: 0.05, distance_method: "none" }), false);
  assert.equal(captureMeetsBar({ ...base, sample_spread_m: 0.05, distance_m: 40 }), false); // past hardMax
  assert.equal(captureMeetsBar({ ...base, sample_spread_m: 0.05, distance_m: null }), false);
  assert.equal(captureMeetsBar(null), false);
});
