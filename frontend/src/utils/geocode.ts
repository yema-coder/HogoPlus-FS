import * as Location from "expo-location";
import { Platform } from "react-native";

/** Reverse-geocode on-device (no API cost) into a short readable address.
 * NEVER throws and NEVER blocks submit — returns null on any failure. */
export async function reverseGeocode(lat: number, lng: number): Promise<string | null> {
  if (Platform.OS === "web") return null; // Geocoding API removed on web in SDK 49
  try {
    const results = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lng });
    const a = results[0];
    if (!a) return null;
    const parts: string[] = [];
    for (const p of [a.name, a.street, a.district, a.subregion, a.city]) {
      if (p && !parts.some((x) => x.toLowerCase() === p.toLowerCase())) parts.push(p);
    }
    const line = parts.slice(0, 4).join(", ").trim();
    return line.length > 0 ? line.slice(0, 300) : null;
  } catch {
    return null;
  }
}
