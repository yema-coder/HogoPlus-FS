/**
 * v1.0.25 LIVE WORKER PRESENCE — battery-friendly shift tracker.
 *
 * HARD RULES (owner-mandated):
 *  - Tracking runs ONLY between punch-in and punch-out, auto-stops at
 *    shift end + 30 min grace (server refuses pings outside a shift anyway).
 *  - FOREGROUND service only: no ACCESS_BACKGROUND_LOCATION, no iOS background
 *    modes. On iOS tracking runs while the app is open (honest limitation).
 *  - BLE zone first, GPS only when no beacon is heard.
 *  - Change-based upload + 5-min heartbeat; offline queue replays idempotently
 *    (client_ping_id dedupe server-side).
 *  - "Tracking stopped" is reported honestly when the worker stops it.
 */
import * as Battery from "expo-battery";
import Constants from "expo-constants";
import * as Location from "expo-location";
import { Platform } from "react-native";

import { ApiError } from "@/src/api/client";
import { presenceMyStatus, presencePing } from "@/src/api/endpoints";
import { getBleScanner } from "@/src/ble/BleScanner";
import { getRegistryFast } from "@/src/ble/zoneSession";
import { storage } from "@/src/utils/storage";

export const PRESENCE_TASK = "hogo-presence-track";
const Q_KEY = "hogo.presence.queue.v1";
const ST_KEY = "hogo.presence.state.v1";
const HEARTBEAT_MS = 290_000; // resend even without change (5 min − jitter)
const QUEUE_CAP = 200; // ~16 h of pings — enough for any offline shift
const BLE_SCAN_MS = 6_000;
const APP_VERSION = Constants.expoConfig?.version ?? "0.0.0";

interface TrackState {
  active: boolean;
  stopAfter: string | null;
  lastKey: string | null;
  lastSentAt: number;
}

interface QueuedPing {
  client_ping_id: string;
  source: "beacon" | "gps" | "stopped";
  zone_key?: string | null;
  lat?: number | null;
  lng?: number | null;
  accuracy_m?: number | null;
  battery_pct?: number | null;
  app_version?: string;
  client_ts?: string;
}

const IDLE: TrackState = { active: false, stopAfter: null, lastKey: null, lastSentAt: 0 };

async function readState(): Promise<TrackState> {
  try {
    const raw = await storage.getItem<string>(ST_KEY, "");
    return raw ? (JSON.parse(String(raw)) as TrackState) : { ...IDLE };
  } catch {
    return { ...IDLE };
  }
}
const writeState = (s: TrackState) => storage.setItem(ST_KEY, JSON.stringify(s)).catch(() => undefined);

function pingId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

async function readQueue(): Promise<QueuedPing[]> {
  try {
    const raw = await storage.getItem<string>(Q_KEY, "");
    return raw ? (JSON.parse(String(raw)) as QueuedPing[]) : [];
  } catch {
    return [];
  }
}
const writeQueue = (q: QueuedPing[]) =>
  storage.setItem(Q_KEY, JSON.stringify(q.slice(-QUEUE_CAP))).catch(() => undefined);

/** Flush the offline queue. Server gate rejections (403/409) stop tracking —
 * the server is the source of truth about who may be tracked. */
async function flushQueue(): Promise<void> {
  const q = await readQueue();
  if (q.length === 0) return;
  try {
    await presencePing(q.slice(0, 50));
    await writeQueue(q.slice(50));
    if (q.length > 50) await flushQueue();
  } catch (e) {
    if (e instanceof ApiError && (e.status === 403 || e.status === 409)) {
      await writeQueue([]);
      await stopTracking("server_refused");
    }
    // network / 429: keep the queue, replay later (idempotent by client_ping_id)
  }
}

async function batteryPct(): Promise<number | null> {
  try {
    const level = await Battery.getBatteryLevelAsync();
    if (level === null || level < 0) return null;
    return Math.max(0, Math.min(100, Math.round(level * 100)));
  } catch {
    return null;
  }
}

/** One tracking cycle: BLE zone first, GPS fallback; change-based + heartbeat. */
export async function presenceCycle(loc: Location.LocationObject | null): Promise<void> {
  const state = await readState();
  if (!state.active) return;
  if (state.stopAfter && Date.now() > Date.parse(state.stopAfter)) {
    await stopTracking("shift_end");
    return;
  }

  // BLE zone first
  let zoneKey: string | null = null;
  try {
    const registry = await getRegistryFast();
    if (registry) {
      const hit = await getBleScanner().scan(BLE_SCAN_MS, {
        macs: registry.macs ?? [],
        ibeacons: registry.ibeacons ?? [],
      });
      if (hit?.ibeacon) {
        zoneKey = `${hit.ibeacon.uuid.toLowerCase()}:${hit.ibeacon.major}:${hit.ibeacon.minor}`;
      } else if (hit?.mac) {
        zoneKey = `mac:${hit.mac.toLowerCase()}`;
      }
    }
  } catch {
    zoneKey = null; // scan failure = no beacon; GPS decides
  }

  let ping: QueuedPing | null = null;
  const now = new Date().toISOString();
  if (zoneKey) {
    ping = { client_ping_id: pingId(), source: "beacon", zone_key: zoneKey, client_ts: now };
  } else if (loc) {
    ping = {
      client_ping_id: pingId(),
      source: "gps",
      lat: loc.coords.latitude,
      lng: loc.coords.longitude,
      accuracy_m: loc.coords.accuracy ?? null,
      client_ts: now,
    };
  }
  if (!ping) return; // no beacon AND no fix — send nothing; dashboard shows stale honestly

  const key = zoneKey ?? `gps:${ping.lat!.toFixed(3)},${ping.lng!.toFixed(3)}`;
  const changed = key !== state.lastKey;
  const heartbeatDue = Date.now() - state.lastSentAt >= HEARTBEAT_MS;
  if (!changed && !heartbeatDue) return;

  ping.battery_pct = await batteryPct();
  ping.app_version = APP_VERSION;
  const q = await readQueue();
  q.push(ping);
  await writeQueue(q);
  await writeState({ ...state, lastKey: key, lastSentAt: Date.now() });
  await flushQueue();
}

let webTimer: ReturnType<typeof setInterval> | null = null;

async function nativeUpdatesRunning(): Promise<boolean> {
  try {
    return await Location.hasStartedLocationUpdatesAsync(PRESENCE_TASK);
  } catch {
    return false;
  }
}

/** Start tracking. Assumes consent already recorded — the server re-checks
 * every gate anyway. Returns false when not expected / permissions missing. */
export async function startTracking(): Promise<boolean> {
  let status: Awaited<ReturnType<typeof presenceMyStatus>>;
  try {
    status = await presenceMyStatus();
  } catch {
    return false;
  }
  if (!status.tracking_expected) return false;
  // shift end + 30 min grace already passed — never start (honest auto-stop rule)
  if (status.stop_after && Date.now() > Date.parse(status.stop_after)) return false;

  const perm = await Location.getForegroundPermissionsAsync();
  if (!perm.granted) {
    const req = perm.canAskAgain ? await Location.requestForegroundPermissionsAsync() : perm;
    if (!req.granted) return false;
  }

  await writeState({
    active: true,
    stopAfter: status.stop_after ?? null,
    lastKey: null,
    lastSentAt: 0,
  });

  if (Platform.OS === "web") {
    if (webTimer) clearInterval(webTimer);
    const tick = async () => {
      let loc: Location.LocationObject | null = null;
      try {
        loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      } catch {
        loc = null;
      }
      await presenceCycle(loc);
    };
    webTimer = setInterval(() => void tick(), 90_000);
    void tick();
    return true;
  }

  if (!(await nativeUpdatesRunning())) {
    await Location.startLocationUpdatesAsync(PRESENCE_TASK, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: 90_000,
      distanceInterval: 60,
      pausesUpdatesAutomatically: false,
      showsBackgroundLocationIndicator: false,
      foregroundService: {
        notificationTitle: "HogoPlus — शिफ्ट ट्रॅकिंग चालू",
        notificationBody: "फक्त तुमच्या शिफ्ट दरम्यान · Only during your shift",
        notificationColor: "#0B4F6C",
        killServiceOnDestroy: true,
      },
    });
  }
  // immediate first ping so the dashboard sees the worker within seconds
  try {
    const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    void presenceCycle(loc);
  } catch {
    void presenceCycle(null);
  }
  return true;
}

/** Stop tracking. `sendStopped` reports the stop honestly to the dashboard
 * (used when the worker turns tracking off mid-shift — never for punch-out,
 * where the worker simply leaves the on-shift list). */
export async function stopTracking(
  _reason: "punch_out" | "shift_end" | "server_refused" | "user",
  sendStopped = false,
): Promise<void> {
  if (webTimer) {
    clearInterval(webTimer);
    webTimer = null;
  }
  if (Platform.OS !== "web" && (await nativeUpdatesRunning())) {
    try {
      await Location.stopLocationUpdatesAsync(PRESENCE_TASK);
    } catch {
      // already stopped
    }
  }
  await writeState({ ...IDLE });
  if (sendStopped) {
    try {
      await presencePing([
        {
          client_ping_id: pingId(),
          source: "stopped",
          battery_pct: await batteryPct(),
          app_version: APP_VERSION,
          client_ts: new Date().toISOString(),
        },
      ]);
    } catch {
      // best effort — server may already refuse
    }
  }
}

export type PunchInPresence = "consent" | "started" | "denied" | "off";

/** Called right after a successful punch-in. */
export async function onPunchInSuccess(): Promise<PunchInPresence> {
  try {
    const status = await presenceMyStatus();
    if (!status.enabled || !status.in_pilot) return "off";
    if (status.consent_required) return "consent";
    return (await startTracking()) ? "started" : "denied";
  } catch {
    return "off";
  }
}

/** Called right after a successful punch-out. */
export async function onPunchOut(): Promise<void> {
  await stopTracking("punch_out");
}

/** App-start / home-focus reconciliation: restart after a reboot or process
 * kill while still on shift; stop when the shift is over. */
export async function resumeIfNeeded(): Promise<"active" | "restarted" | "stopped" | "idle"> {
  const state = await readState();
  try {
    const status = await presenceMyStatus();
    if (!status.tracking_expected) {
      if (state.active) {
        await stopTracking("shift_end");
        return "stopped";
      }
      return "idle";
    }
    if (state.active && Platform.OS !== "web" && (await nativeUpdatesRunning())) return "active";
    return (await startTracking()) ? "restarted" : "idle";
  } catch {
    return state.active ? "active" : "idle";
  }
}

export async function isTrackingActive(): Promise<boolean> {
  return (await readState()).active;
}
