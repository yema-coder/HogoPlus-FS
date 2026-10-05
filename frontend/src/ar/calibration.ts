// Admin tape-measure calibration for the AR distance feature (A3). A single
// multiplicative scale factor corrects a device's systematic bias. Persisted in
// AsyncStorage and applied to both the live reading and the captured metadata.
// Pure where possible so the ratio math is unit-testable.

import { storage } from "@/src/utils/storage";
import type { DistanceReading } from "./types";

const KEY = "hogo.ar.calib";
const MIN_SCALE = 0.2;
const MAX_SCALE = 5;

export interface ArCalibration {
  scale: number; // multiply a raw distance by this
  samples: number; // how many ground-truth pairs informed it
  updatedAt: number | null;
}

const DEFAULT: ArCalibration = { scale: 1, samples: 0, updatedAt: null };
let cache: ArCalibration = { ...DEFAULT };

function clamp(s: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));
}

export async function loadCalibration(): Promise<ArCalibration> {
  const raw = await storage.getItem<string>(KEY, "");
  if (raw) {
    try {
      const p = JSON.parse(raw) as Partial<ArCalibration>;
      if (typeof p.scale === "number" && Number.isFinite(p.scale) && p.scale > 0) {
        cache = { scale: clamp(p.scale), samples: p.samples ?? 0, updatedAt: p.updatedAt ?? null };
      }
    } catch {
      // corrupt value — keep the default
    }
  }
  return cache;
}

export function getCalibrationSync(): ArCalibration {
  return cache;
}

export async function saveCalibration(scale: number, samples: number): Promise<ArCalibration> {
  cache = { scale: clamp(scale), samples, updatedAt: Date.now() };
  await storage.setItem(KEY, JSON.stringify(cache));
  return cache;
}

export async function resetCalibration(): Promise<void> {
  cache = { ...DEFAULT };
  await storage.removeItem(KEY);
}

/** Median of truth/measured ratios → the multiplicative correction factor. */
export function computeScale(pairs: { measured: number; truth: number }[]): number {
  const ratios = pairs
    .filter((p) => p.measured > 0 && p.truth > 0)
    .map((p) => p.truth / p.measured)
    .sort((a, b) => a - b);
  if (ratios.length === 0) return 1;
  const m = Math.floor(ratios.length / 2);
  const med = ratios.length % 2 ? ratios[m] : (ratios[m - 1] + ratios[m]) / 2;
  return clamp(med);
}

/** Apply the active calibration to a live reading (distance + uncertainty). */
export function applyCalibration(r: DistanceReading): DistanceReading {
  const s = cache.scale;
  if (s === 1 || r.distanceM == null) return r;
  return {
    ...r,
    distanceM: Math.round(r.distanceM * s * 100) / 100,
    uncertaintyM:
      r.uncertaintyM != null ? Math.round(r.uncertaintyM * s * 100) / 100 : r.uncertaintyM,
  };
}
