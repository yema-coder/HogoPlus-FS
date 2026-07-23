import Constants from "expo-constants";
import { PermissionsAndroid, Platform } from "react-native";

export interface IBeaconId {
  uuid: string;
  major: number;
  minor: number;
}

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
}

/** Minimal, dependency-free base64 → byte array (Hermes-safe). */
function base64ToBytes(b64: string): number[] {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const clean = b64.replace(/[^A-Za-z0-9+/]/g, "");
  const out: number[] = [];
  for (let i = 0; i < clean.length; i += 4) {
    const e = [0, 1, 2, 3].map((k) => chars.indexOf(clean[i + k] ?? "A"));
    const n = (e[0] << 18) | (e[1] << 12) | (e[2] << 6) | e[3];
    out.push((n >> 16) & 0xff);
    if (clean[i + 2] !== undefined && (i + 2) < clean.length) out.push((n >> 8) & 0xff);
    if (clean[i + 3] !== undefined && (i + 3) < clean.length) out.push(n & 0xff);
  }
  return out;
}

/**
 * Parse the standard Apple iBeacon manufacturer-data layout from ble-plx's
 * base64 `manufacturerData` (which includes the 2-byte company id):
 *   [0..1] company id 0x4C 0x00 · [2] 0x02 (type) · [3] 0x15 (len) ·
 *   [4..19] UUID · [20..21] major (BE) · [22..23] minor (BE) · [24] tx power.
 */
function parseIBeacon(b64?: string | null): IBeaconId | null {
  if (!b64) return null;
  let b: number[];
  try {
    b = base64ToBytes(b64);
  } catch {
    return null;
  }
  if (b.length < 25) return null;
  if (b[0] !== 0x4c || b[1] !== 0x00 || b[2] !== 0x02 || b[3] !== 0x15) return null;
  const hex = b.slice(4, 20).map((x) => x.toString(16).padStart(2, "0")).join("");
  const uuid = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  return { uuid, major: (b[20] << 8) | b[21], minor: (b[22] << 8) | b[23] };
}

class NoopBleScanner implements BleScanner {
  readonly isReal = false;

  async scan(): Promise<BleBeaconHit | null> {
    return null;
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
    // Dual-mode: match device.id against registered MACs (Android) OR the parsed
    // iBeacon triple against registered UUID/Major/Minor. iOS note: CoreBluetooth
    // filters raw iBeacon frames, so iBeacon ranging is Android-reliable here.
    const macSet = new Set((registry.macs ?? []).map((m) => m.trim().toUpperCase()));
    const ibKey = (i: IBeaconId) => `${i.uuid.trim().toLowerCase()}:${i.major}:${i.minor}`;
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
          { allowDuplicates: false },
          // ble-plx callback types unavailable at build time
          (error: any, device: any) => {
            if (error) {
              clearTimeout(timer);
              finish();
              return;
            }
            if (!device) return;
            const rssi = typeof device.rssi === "number" ? device.rssi : -100;
            let hit: BleBeaconHit | null = null;
            const mac = device.id ? String(device.id).toUpperCase() : "";
            if (mac && macSet.has(mac)) {
              hit = { mac };
            } else {
              const ib = parseIBeacon(device.manufacturerData);
              if (ib && ibSet.has(ibKey(ib))) hit = { ibeacon: ib };
            }
            if (hit && (!best || rssi > best.rssi)) {
              best = { hit, rssi };
            }
          },
        );
      } catch {
        clearTimeout(timer);
        resolve(null);
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

/**
 * Lazily request Android 12+ Nearby-devices permissions right before the first
 * real BLE scan (not at onboarding). Returns true when scanning is allowed.
 * Denial is graceful: the punch flow simply skips the zone step.
 */
export async function ensureBlePermissions(): Promise<boolean> {
  if (Platform.OS !== "android") return true;
  if (!getBleScanner().isReal) return true; // Expo Go noop scanner — nothing to ask
  if (Number(Platform.Version) < 31) return true; // pre-Android-12: location covers BLE
  try {
    const res = await PermissionsAndroid.requestMultiple([
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
    ]);
    return Object.values(res).every((v) => v === PermissionsAndroid.RESULTS.GRANTED);
  } catch {
    return false;
  }
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
