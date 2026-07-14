import Constants from "expo-constants";
import { Platform } from "react-native";

export interface BleBeaconHit {
  beaconId: string;
  zone: string | null;
}

export interface BleScanner {
  readonly isReal: boolean;
  /** Scan for nearby factory beacons; resolves with the strongest hit or null. */
  scan(timeoutMs: number): Promise<BleBeaconHit | null>;
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- third-party module loaded dynamically, no types at build time
  private manager: any;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- see above
  constructor(manager: any) {
    this.manager = manager;
  }

  scan(timeoutMs: number): Promise<BleBeaconHit | null> {
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
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- ble-plx callback types unavailable
          (error: any, device: any) => {
            if (error) {
              clearTimeout(timer);
              finish();
              return;
            }
            if (device && (device.localName || device.name)) {
              const rssi = typeof device.rssi === "number" ? device.rssi : -100;
              if (!best || rssi > best.rssi) {
                best = {
                  hit: { beaconId: String(device.id), zone: device.localName ?? device.name ?? null },
                  rssi,
                };
              }
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
