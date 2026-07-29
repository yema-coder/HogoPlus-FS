/**
 * Pure iBeacon frame extraction + registry matching — NO react-native imports so it
 * can be unit-tested under plain node (scripts/test-ibeacon-parse.js).
 *
 * v1.0.16 ROOT-CAUSE NOTE (why extraction changed):
 * react-native-ble-plx's Android adapter (AdvertisementData.parseManufacturerData)
 * keeps ONE `manufacturerData` field and OVERWRITES it for EVERY 0xFF AD structure
 * in the merged scan record. Vendor beacons interleave their own manufacturer frame
 * (used by the vendor config app) in the SCAN RESPONSE — Android merges ADV+SCAN_RSP
 * into a single record, the vendor frame comes after the Apple iBeacon frame, and it
 * CLOBBERS the 4C 00 02 15 payload before JS ever sees it. Fix: parse the iBeacon out
 * of `rawScanRecord` (the full merged record, also exposed by ble-plx) by scanning for
 * the Apple iBeacon signature at ANY offset, collecting ALL frames, not just the last.
 */

export interface IBeaconId {
  uuid: string;
  major: number;
  minor: number;
}

export interface RegistryIBeacon {
  uuid: string;
  major: number;
  minor: number;
}

/** Minimal, dependency-free base64 → byte array (Hermes-safe). */
export function base64ToBytes(b64: string): number[] {
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
 * Extract EVERY Apple iBeacon frame from a base64 payload — works on both a bare
 * ble-plx `manufacturerData` (company id 4C 00 + 02 15 + payload) AND a full
 * `rawScanRecord` (AD structures, any frame order, vendor frames interleaved).
 * Signature scan: 4C 00 02 15 at ANY offset with >= 20 bytes remaining
 * (16 UUID + 2 major + 2 minor; tx-power byte optional).
 * UUIDs are emitted lowercase hyphenated 8-4-4-4-12.
 */
export function extractIBeacons(b64?: string | null): IBeaconId[] {
  if (!b64) return [];
  let b: number[];
  try {
    b = base64ToBytes(b64);
  } catch {
    return [];
  }
  const found: IBeaconId[] = [];
  const seen = new Set<string>();
  for (let i = 0; i + 24 <= b.length; i++) {
    if (b[i] !== 0x4c || b[i + 1] !== 0x00 || b[i + 2] !== 0x02 || b[i + 3] !== 0x15) continue;
    const u = b.slice(i + 4, i + 20).map((x) => x.toString(16).padStart(2, "0")).join("");
    const uuid = `${u.slice(0, 8)}-${u.slice(8, 12)}-${u.slice(12, 16)}-${u.slice(16, 20)}-${u.slice(20)}`;
    const ib: IBeaconId = {
      uuid,
      major: (b[i + 20] << 8) | b[i + 21],
      minor: (b[i + 22] << 8) | b[i + 23],
    };
    const k = ibKey(ib);
    if (!seen.has(k)) {
      seen.add(k);
      found.push(ib);
    }
  }
  return found;
}

/**
 * Canonical case-insensitive, type-coerced match key: uuid lowercased+trimmed,
 * major/minor forced to Number (defends against string-typed registry values).
 */
export const ibKey = (i: { uuid: string; major: number | string; minor: number | string }): string =>
  `${String(i.uuid).trim().toLowerCase()}:${Number(i.major)}:${Number(i.minor)}`;

export type CandidateVerdict = "matched" | "uuid_mismatch" | "major_mismatch" | "minor_not_registered";

/** Explain WHY a parsed candidate did / didn't match the registry (diagnostics). */
export function classifyCandidate(ib: IBeaconId, registry: RegistryIBeacon[]): CandidateVerdict {
  const u = ib.uuid.trim().toLowerCase();
  const sameUuid = registry.filter((r) => String(r.uuid).trim().toLowerCase() === u);
  if (sameUuid.length === 0) return "uuid_mismatch";
  const sameMajor = sameUuid.filter((r) => Number(r.major) === Number(ib.major));
  if (sameMajor.length === 0) return "major_mismatch";
  if (!sameMajor.some((r) => Number(r.minor) === Number(ib.minor))) return "minor_not_registered";
  return "matched";
}
