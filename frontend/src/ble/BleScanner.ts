import Constants from "expo-constants";
import { PermissionsAndroid, Platform } from "react-native";

import {
  classifyCandidate,
  extractIBeacons,
  ibKey,
  type IBeaconId,
} from "./ibeaconParse";

export type { IBeaconId };

export interface BleBeaconHit {
  /** MAC of the matched beacon (Android exposes device.id as MAC). */
  mac?: string;
  /** iBeacon triple of the matched beacon (parsed from manufacturer data). */
  ibeacon?: IBeaconId;
}

export interface BeaconRegistry {
  /** Registered active MAC addresses (case-insensitive match). */
  macs: string[];
  /** Registered active iBeacon triples (UUID case-insensitive match). */
  ibeacons: IBeaconId[];
}

export interface BleScanner {
  readonly isReal: boolean;
  /**
   * Scan for nearby vendor beacons and match them against the registered list in
   * BOTH modes: MAC (case-insensitive) OR iBeacon (UUID/Major/Minor). Resolves with
   * the strongest-RSSI match or null. Never throws — failure yields null.
   */
  scan(timeoutMs: number, registry: BeaconRegistry): Promise<BleBeaconHit | null>;
  /**
   * v1.0.16 DIAGNOSTIC scan: collects EVERY device seen (duplicates merged per id,
   * frames accumulated so interleaved advertisements are all captured) with parsed
   * iBeacon candidates and a per-candidate rejection verdict. Never throws.
   */
  scanDiagnostics(timeoutMs: number, registry: BeaconRegistry): Promise<BleDiagScan>;
}

export interface BleDiagDevice {
  id: string;
  name: string | null;
  rssi: number | null;
  frames: number;
  /** distinct manufacturerData payloads seen (base64, truncated) */
  mfg: string[];
  /** distinct rawScanRecord payloads seen (base64, truncated) */
  raw: string[];
  ibeacons: { uuid: string; major: number; minor: number; verdict: string }[];
  verdict: string; // matched | mac_matched | uuid_mismatch | major_mismatch | minor_not_registered | no_ibeacon_frame | no_mfg_data
}

export interface BleDiagScan {
  supported: boolean;
  scanMs: number;
  callbacks: number;
  devicesSeen: number;
  matchedCount: number;
  error: string | null;
  devices: BleDiagDevice[];
}

class NoopBleScanner implements BleScanner {
  readonly isReal = false;

  async scan(): Promise<BleBeaconHit | null> {
    return null;
  }

  async scanDiagnostics(): Promise<BleDiagScan> {
    return {
      supported: false,
      scanMs: 0,
      callbacks: 0,
      devicesSeen: 0,
      matchedCount: 0,
      error: "BLE not available (Expo Go / web)",
      devices: [],
    };
  }
}

/**
 * Real scanner backed by react-native-ble-plx. The module is loaded lazily via
 * require() so that Expo Go (where the native module is absent) never crashes —
 * any failure falls back to the noop scanner.
 */
class RealBleScanner implements BleScanner {
  readonly isReal = true;
  // third-party module loaded dynamically, no types at build time
  private manager: any;

  constructor(manager: any) {
    this.manager = manager;
  }

  scan(timeoutMs: number, registry: BeaconRegistry): Promise<BleBeaconHit | null> {
    // Dual-mode: match device.id against registered MACs (Android) OR any parsed
    // iBeacon triple against registered UUID/Major/Minor. iOS note: CoreBluetooth
    // filters raw iBeacon frames, so iBeacon ranging is Android-reliable here.
    const macSet = new Set((registry.macs ?? []).map((m) => m.trim().toUpperCase()));
    const ibSet = new Set((registry.ibeacons ?? []).map(ibKey));
    if (macSet.size === 0 && ibSet.size === 0) return Promise.resolve(null);
    return new Promise((resolve) => {
      let best: { hit: BleBeaconHit; rssi: number } | null = null;
      const finish = () => {
        try {
          this.manager.stopDeviceScan();
        } catch {
          // ignore
        }
        resolve(best ? best.hit : null);
      };
      const timer = setTimeout(finish, timeoutMs);
      try {
        this.manager.startDeviceScan(
          null,
          // scanMode 2 = LOW_LATENCY: continuous radio listening for the whole window.
          // The Android default duty cycle (~0.5s listening per 5s) can miss a beacon's
          // advertising interval entirely inside a short window (field failure 2026-07-27).
          { allowDuplicates: false, scanMode: 2 },
          // ble-plx callback types unavailable at build time
          (error: any, device: any) => {
            if (error) {
              clearTimeout(timer);
              finish();
              return;
            }
            if (!device) return;
            let hit: BleBeaconHit | null = null;
            const mac = device.id ? String(device.id).toUpperCase() : "";
            if (mac && macSet.has(mac)) {
              hit = { mac };
            } else {
              // v1.0.16: parse from rawScanRecord (full merged ADV+SCAN_RSP record) —
              // ble-plx's single manufacturerData field is CLOBBERED by vendor frames
              // interleaved in the scan response, hiding the Apple iBeacon frame.
              const candidates = [
                ...extractIBeacons(device.rawScanRecord),
                ...extractIBeacons(device.manufacturerData),
              ];
              const ib = candidates.find((c) => ibSet.has(ibKey(c)));
              if (ib) hit = { ibeacon: ib };
            }
            if (hit) {
              // EARLY EXIT on the first registered match — any registered beacon
              // proves presence; no need to burn the rest of the scan window.
              best = { hit, rssi: typeof device.rssi === "number" ? device.rssi : -100 };
              clearTimeout(timer);
              finish();
            }
          },
        );
      } catch {
        clearTimeout(timer);
        resolve(null);
      }
    });
  }

  scanDiagnostics(timeoutMs: number, registry: BeaconRegistry): Promise<BleDiagScan> {
    const macSet = new Set((registry.macs ?? []).map((m) => m.trim().toUpperCase()));
    const regIb = registry.ibeacons ?? [];
    const started = Date.now();
    type Acc = {
      id: string;
      name: string | null;
      rssi: number | null;
      frames: number;
      mfg: Set<string>;
      raw: Set<string>;
      cands: Map<string, IBeaconId>;
    };
    const acc = new Map<string, Acc>();
    let callbacks = 0;
    let error: string | null = null;
    return new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        try {
          this.manager.stopDeviceScan();
        } catch {
          // ignore
        }
        const devices: BleDiagDevice[] = [...acc.values()].map((d) => {
          const ibeacons = [...d.cands.values()].map((c) => ({
            ...c,
            verdict: classifyCandidate(c, regIb),
          }));
          let verdict: string;
          if (macSet.has(d.id.toUpperCase())) verdict = "mac_matched";
          else if (ibeacons.some((i) => i.verdict === "matched")) verdict = "matched";
          else if (ibeacons.some((i) => i.verdict === "minor_not_registered")) verdict = "minor_not_registered";
          else if (ibeacons.some((i) => i.verdict === "major_mismatch")) verdict = "major_mismatch";
          else if (ibeacons.length > 0) verdict = "uuid_mismatch";
          else if (d.mfg.size > 0 || d.raw.size > 0) verdict = "no_ibeacon_frame";
          else verdict = "no_mfg_data";
          return {
            id: d.id,
            name: d.name,
            rssi: d.rssi,
            frames: d.frames,
            mfg: [...d.mfg],
            raw: [...d.raw],
            ibeacons,
            verdict,
          };
        });
        const rank = (v: string) => (v === "matched" || v === "mac_matched" ? 0 : v === "no_mfg_data" ? 2 : 1);
        devices.sort((a, b) => rank(a.verdict) - rank(b.verdict) || (b.rssi ?? -999) - (a.rssi ?? -999));
        resolve({
          supported: true,
          scanMs: Date.now() - started,
          callbacks,
          devicesSeen: devices.length,
          matchedCount: devices.filter((d) => d.verdict === "matched" || d.verdict === "mac_matched").length,
          error,
          devices: devices.slice(0, 50),
        });
      };
      const timer = setTimeout(finish, timeoutMs);
      try {
        this.manager.startDeviceScan(
          null,
          // duplicates ON: we WANT every callback so interleaved frames from the same
          // beacon (iBeacon frame + vendor config frame) are all captured and merged.
          { allowDuplicates: true, scanMode: 2 },
          (err: any, device: any) => {
            if (err) {
              error = String(err?.message ?? err);
              clearTimeout(timer);
              finish();
              return;
            }
            if (!device) return;
            callbacks += 1;
            const id = String(device.id ?? "?");
            let d = acc.get(id);
            if (!d) {
              d = { id, name: null, rssi: null, frames: 0, mfg: new Set(), raw: new Set(), cands: new Map() };
              acc.set(id, d);
            }
            d.frames += 1;
            if (typeof device.rssi === "number") d.rssi = device.rssi;
            if (device.name) d.name = String(device.name);
            if (device.manufacturerData) d.mfg.add(String(device.manufacturerData).slice(0, 64));
            if (device.rawScanRecord) d.raw.add(String(device.rawScanRecord).slice(0, 96));
            for (const c of [...extractIBeacons(device.rawScanRecord), ...extractIBeacons(device.manufacturerData)]) {
              d.cands.set(ibKey(c), c);
            }
          },
        );
      } catch (e) {
        error = String(e);
        clearTimeout(timer);
        finish();
      }
    });
  }
}

let cached: BleScanner | null = null;

/** Build the attendance/incident BLE payload fields from a scan hit (or null). */
export function beaconPayload(hit: BleBeaconHit | null): Record<string, unknown> {
  if (hit?.mac) return { ble_beacon_id: hit.mac };
  if (hit?.ibeacon) {
    return {
      ble_ibeacon_uuid: hit.ibeacon.uuid,
      ble_ibeacon_major: hit.ibeacon.major,
      ble_ibeacon_minor: hit.ibeacon.minor,
    };
  }
  return { ble_beacon_id: null };
}

export function getBleScanner(): BleScanner {
  if (cached) return cached;
  const inExpoGo = Constants.appOwnership === "expo";
  if (inExpoGo || Platform.OS === "web") {
    cached = new NoopBleScanner();
    return cached;
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- intentional lazy native import
    const blePlx = require("react-native-ble-plx") as { BleManager?: new () => unknown };
    if (blePlx.BleManager) {
      cached = new RealBleScanner(new blePlx.BleManager());
      return cached;
    }
  } catch {
    // native module missing — fall through to noop
  }
  cached = new NoopBleScanner();
  return cached;
}

/** Granular Nearby-devices permission state (Android 12+). */
export type BlePermissionStatus = "granted" | "denied" | "blocked" | "unavailable";

/** Check (WITHOUT prompting) whether BLE scanning is allowed right now. */
export async function checkBlePermissions(): Promise<BlePermissionStatus> {
  if (Platform.OS !== "android") return "granted";
  if (!getBleScanner().isReal) return "unavailable"; // Expo Go / web — no radio access
  if (Number(Platform.Version) < 31) return "granted"; // pre-Android-12: FINE_LOCATION covers scanning
  try {
    const scan = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN);
    const conn = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT);
    // v1.0.16: BLUETOOTH_SCAN is declared WITHOUT neverForLocation (so iBeacon frames
    // aren't OS-filtered) — Android 12+ therefore also requires PRECISE location to
    // deliver scan results. An "approximate only" grant silently yields zero results.
    const fine = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);
    return scan && conn && fine ? "granted" : "denied";
  } catch {
    return "denied";
  }
}

/**
 * Request Android 12+ Nearby-devices permissions. Returns granular status so
 * callers can FAIL CLOSED with a clear message ("blocked" = user chose
 * "Don't ask again" → only Settings can fix it).
 */
export async function requestBlePermissions(): Promise<BlePermissionStatus> {
  if (Platform.OS !== "android") return "granted";
  if (!getBleScanner().isReal) return "unavailable";
  if (Number(Platform.Version) < 31) return "granted";
  try {
    const res = await PermissionsAndroid.requestMultiple([
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
      // required alongside a no-neverForLocation BLUETOOTH_SCAN for scan results;
      // also upgrades an "approximate" location grant to precise.
      PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
    ]);
    const values = Object.values(res);
    if (values.every((v) => v === PermissionsAndroid.RESULTS.GRANTED)) return "granted";
    if (values.some((v) => v === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN)) return "blocked";
    return "denied";
  } catch {
    return "denied";
  }
}

/** Boolean wrapper for opportunistic (non-blocking) scans, e.g. incident zone tag. */
export async function ensureBlePermissions(): Promise<boolean> {
  const s = await requestBlePermissions();
  return s === "granted" || s === "unavailable";
}

/**
 * Prompt 17 Part D: Bluetooth radio state for the pre-capture guard.
 * 'unknown' (Expo Go / web / errors) is treated as a pass by callers.
 */
export async function getBleState(): Promise<"on" | "off" | "unknown"> {
  const scanner = getBleScanner();
  if (!scanner.isReal) return "unknown";
  try {
    const manager = (scanner as unknown as { manager?: { state?: () => Promise<string> } }).manager;
    if (!manager?.state) return "unknown";
    const state = await manager.state();
    if (state === "PoweredOn") return "on";
    if (state === "PoweredOff") return "off";
    return "unknown";
  } catch {
    return "unknown";
  }
}
