import * as Location from "expo-location";

export interface GpsFix {
  lat: number;
  lng: number;
  /** metres, when the platform reports it */
  accuracy: number | null;
}

export interface GpsResult {
  fix: GpsFix | null;
  /** true when permission is permanently denied (show Open Settings). */
  blocked: boolean;
}

/**
 * Contextual GPS acquisition (called only after clear user intent —
 * reporting an incident or punching in). Never throws, never dead-ends:
 * a null fix simply degrades the flow (incident without GPS / flagged punch).
 */
export async function acquireGps(timeoutMs = 10000): Promise<GpsResult> {
  try {
    let perm = await Location.getForegroundPermissionsAsync();
    if (!perm.granted && perm.canAskAgain) {
      perm = await Location.requestForegroundPermissionsAsync();
    }
    if (!perm.granted) return { fix: null, blocked: !perm.canAskAgain };

    const current = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs)),
    ]);
    if (current) {
      return {
        fix: {
          lat: current.coords.latitude,
          lng: current.coords.longitude,
          accuracy: current.coords.accuracy ?? null,
        },
        blocked: false,
      };
    }
    const last = await Location.getLastKnownPositionAsync();
    return {
      fix: last
        ? { lat: last.coords.latitude, lng: last.coords.longitude, accuracy: last.coords.accuracy ?? null }
        : null,
      blocked: false,
    };
  } catch {
    return { fix: null, blocked: false };
  }
}
