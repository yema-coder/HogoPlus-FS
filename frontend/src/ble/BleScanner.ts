import Constants from "expo-constants";
import { PermissionsAndroid, Platform } from "react-native";

export interface BleBeaconHit {
  /** MAC address of the strongest matched registered beacon (normalized uppercase). */
  mac: string;
}

export interface BleScanner {
  readonly isReal: boolean;
  /**
   * Scan for nearby vendor beacons and match them against the registered MAC list
   * (case-insensitive); resolves with the strongest-RSSI match or null.
   */
  scan(timeoutMs: number, registeredMacs: string[]): Promise<BleBeaconHit | null>;
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

  scan(timeoutMs: number, registeredMacs: string[]): Promise<BleBeaconHit | null> {
    // Vendor beacons are MAC-based (non-configurable): match device.id (the MAC on
    // Android) against the registered list — no iBeacon UUID/major/minor filtering.
    const macSet = new Set(registeredMacs.map((m) => m.trim().toUpperCase()));
    if (macSet.size === 0) return Promise.resolve(null);
    return new Promise((resolve) => {
      let best: { mac: string; rssi: number } | null = null;
      const finish = () => {
        try {
          this.manager.stopDeviceScan();
        } catch {
          // ignore
        }
        resolve(best ? { mac: best.mac } : null);
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
            if (!device?.id) return;
            const mac = String(device.id).toUpperCase();
            if (!macSet.has(mac)) return;
            const rssi = typeof device.rssi === "number" ? device.rssi : -100;
            if (!best || rssi > best.rssi) {
              best = { mac, rssi };
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
