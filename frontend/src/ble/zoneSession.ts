/**
 * v1.0.17 SPEED PACK — shared background zone-scan session used by BOTH the punch
 * and incident flows (single code path, no parallel implementations).
 *
 * Why: v1.0.16 field timing showed the punch flow resolving the zone in ~1 minute,
 * because everything ran SEQUENTIALLY and only started AFTER the selfie:
 * GPS (≤8s) → reverse-geocode → registry fetch (network RTT) → permission → 10s scan
 * → compress → upload → submit. This module pre-warms the scan the moment the screen
 * OPENS, caches the registry locally (10-min TTL, background refresh), scans in
 * successive 5s LOW_LATENCY windows with early exit, and lets callers wait AT MOST a
 * capped few seconds at submit — the user is never held hostage by the scan.
 */
import { beaconRegistry } from "@/src/api/endpoints";
import i18n from "@/src/i18n";
import { storage } from "@/src/utils/storage";

import {
  getBleScanner,
  requestBlePermissions,
  type BleBeaconHit,
  type BlePermissionStatus,
} from "./BleScanner";

type RegistryData = Awaited<ReturnType<typeof beaconRegistry>>;

const CACHE_KEY = "hogo.beaconRegistry.v1"; // { at: epoch_ms, data: RegistryData }
const CACHE_TTL_MS = 10 * 60 * 1000;
const SESSION_MAX_MS = 60_000; // hard cap: session self-terminates
const SCAN_WINDOW_MS = 5_000; // successive windows with early exit

/**
 * Registry with local cache: fresh cache → returned instantly (network refresh runs
 * in the background); expired/missing → one network fetch; network failure → stale
 * cache beats nothing (offline punch still scans against the last known registry).
 */
export async function getRegistryFast(): Promise<RegistryData | null> {
  let cached: { at: number; data: RegistryData } | null = null;
  try {
    const raw = await storage.getItem<string>(CACHE_KEY, "");
    if (raw) cached = JSON.parse(String(raw)) as { at: number; data: RegistryData };
  } catch {
    cached = null;
  }
  const save = (d: RegistryData) =>
    storage.setItem(CACHE_KEY, JSON.stringify({ at: Date.now(), data: d })).catch(() => undefined);
  if (cached && Date.now() - cached.at < CACHE_TTL_MS) {
    void beaconRegistry().then(save).catch(() => undefined); // background refresh
    return cached.data;
  }
  try {
    const d = await beaconRegistry();
    await save(d);
    return d;
  } catch {
    return cached ? cached.data : null;
  }
}

/** Matched-zone label in the user's current language. */
function pickZone(hit: BleBeaconHit, registry: RegistryData): string | null {
  const lang = i18n.language;
  const pick = (e?: { zone_en?: string | null; zone_hi?: string | null; zone_mr?: string | null }) => {
    if (!e) return null;
    const v = lang === "hi" ? e.zone_hi : lang === "mr" ? e.zone_mr : e.zone_en;
    return v ?? e.zone_en ?? null;
  };
  if (hit.ibeacon) {
    const k = hit.ibeacon;
    return pick(
      registry.ibeacons?.find(
        (b) => b.uuid.toLowerCase() === k.uuid.toLowerCase() && b.major === k.major && b.minor === k.minor,
      ),
    );
  }
  if (hit.mac) {
    return pick(registry.macs_detail?.find((m) => m.mac.toUpperCase() === hit.mac!.toUpperCase()));
  }
  return null;
}

export interface ZoneTimings {
  startedAt: number;
  permissionMs?: number;
  registryMs?: number;
  /** ms from session start to first registered match */
  firstMatchMs?: number;
}

export interface ZoneSession {
  getHit(): BleBeaconHit | null;
  getZone(): string | null;
  readonly timings: ZoneTimings;
  /** resolves when the permission request settles (fail-closed callers await this) */
  permissionReady: Promise<BlePermissionStatus>;
  /** resolve with the hit as soon as matched, or with the current hit after maxWaitMs */
  waitForHit(maxWaitMs: number): Promise<BleBeaconHit | null>;
  /** fires immediately if already matched; otherwise once on the first match */
  onceMatched(cb: (hit: BleBeaconHit, zone: string | null) => void): void;
  /** subscribe to state changes (chip updates); returns unsubscribe */
  onUpdate(cb: () => void): () => void;
  stop(): void;
}

class ZoneSessionImpl implements ZoneSession {
  readonly timings: ZoneTimings = { startedAt: Date.now() };
  permissionReady: Promise<BlePermissionStatus>;
  private resolvePermission!: (s: BlePermissionStatus) => void;
  private hit: BleBeaconHit | null = null;
  private zone: string | null = null;
  private stopped = false;
  private subs = new Set<() => void>();
  private matchCbs: ((hit: BleBeaconHit, zone: string | null) => void)[] = [];
  private waiters: ((h: BleBeaconHit | null) => void)[] = [];

  constructor() {
    this.permissionReady = new Promise((r) => {
      this.resolvePermission = r;
    });
  }

  getHit() {
    return this.hit;
  }

  getZone() {
    return this.zone;
  }

  onUpdate(cb: () => void) {
    this.subs.add(cb);
    return () => this.subs.delete(cb);
  }

  onceMatched(cb: (hit: BleBeaconHit, zone: string | null) => void) {
    if (this.hit) cb(this.hit, this.zone);
    else this.matchCbs.push(cb);
  }

  waitForHit(maxWaitMs: number): Promise<BleBeaconHit | null> {
    if (this.hit || this.stopped) return Promise.resolve(this.hit);
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(this.hit), maxWaitMs);
      this.waiters.push((h) => {
        clearTimeout(timer);
        resolve(h);
      });
    });
  }

  stop() {
    if (this.stopped) return;
    this.stopped = true;
    const w = this.waiters.splice(0);
    for (const fn of w) fn(this.hit);
    this.notify();
  }

  private notify() {
    for (const cb of this.subs) cb();
  }

  async run(): Promise<void> {
    const scanner = getBleScanner();
    if (!scanner.isReal) {
      this.resolvePermission("unavailable");
      this.stop();
      return;
    }
    let t = Date.now();
    let perm: BlePermissionStatus;
    try {
      perm = await requestBlePermissions();
    } catch {
      perm = "denied";
    }
    this.timings.permissionMs = Date.now() - t;
    this.resolvePermission(perm);
    if (perm !== "granted") {
      this.stop();
      return;
    }
    t = Date.now();
    const registry = await getRegistryFast();
    this.timings.registryMs = Date.now() - t;
    if (
      this.stopped ||
      !registry ||
      ((registry.ibeacons?.length ?? 0) === 0 && (registry.macs?.length ?? 0) === 0)
    ) {
      this.stop();
      return;
    }
    while (!this.stopped && !this.hit && Date.now() - this.timings.startedAt < SESSION_MAX_MS) {
      const h = await scanner.scan(SCAN_WINDOW_MS, registry);
      if (this.stopped) return;
      if (h) {
        this.hit = h;
        this.zone = pickZone(h, registry);
        this.timings.firstMatchMs = Date.now() - this.timings.startedAt;
        const waiters = this.waiters.splice(0);
        for (const fn of waiters) fn(h);
        const cbs = this.matchCbs.splice(0);
        for (const cb of cbs) cb(h, this.zone);
        this.notify();
      }
    }
    if (!this.hit) this.stop();
  }
}

// One session at a time: stopDeviceScan() on the shared BleManager is global, so a
// new session (e.g. opening incident capture right after a punch) always stops the
// previous one instead of silently killing each other's scans.
let current: ZoneSessionImpl | null = null;

export function startZoneSession(): ZoneSession {
  current?.stop();
  const s = new ZoneSessionImpl();
  current = s;
  void s.run();
  return s;
}
