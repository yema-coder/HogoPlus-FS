import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Chip } from "../components";
import { useI18n } from "../i18n";

/** v1.0.26 LIVE PRESENCE Phase 2 — shared types + helpers for the presence area. */

export interface Zone { key: string; name_en: string; name_hi: string; name_mr: string; count?: number }
export interface Worker {
  id: string; emp_id: string; full_name: string; department_code: string | null;
  status: string; freshness: string | null; seconds_since: number | null;
  zone_key: string | null; zone_en: string | null; zone_hi: string | null; zone_mr: string | null;
  lat: number | null; lng: number | null; inside_geofence: boolean | null;
  battery_pct: number | null; last_seen: string | null; punched_in_at: string;
}
export interface Snapshot {
  enabled: boolean; generated_at: string; scope?: string;
  geofence?: { lat: number; lng: number; radius_m: number };
  counts?: Record<string, number>; zones?: Zone[]; workers?: Worker[];
}

export const STATUS_TONE: Record<string, "green" | "red" | "amber" | "blue" | undefined> = {
  in_zone: "green", gps_inside: "green", gps_outside: "red",
  stopped: "amber", no_signal: undefined, not_tracked: undefined,
};

export const ALERT_EMOJI: Record<string, string> = {
  outside_geofence: "🚨", gone_dark: "⚠️", low_battery: "🔋", unauthorized_zone: "⛔",
};

export function zoneName(z: { name_en?: string | null; zone_en?: string | null; [k: string]: any }, lang: string): string {
  return z[`name_${lang}`] || z[`zone_${lang}`] || z.name_en || z.zone_en || "—";
}

/** Beacons carry no GPS coordinates (indoor). Zones get a stable, deterministic
 * ring layout inside the geofence so counts are glanceable on the map. */
export function zonePositions(zones: { key: string }[], center: [number, number], radiusM: number): Record<string, [number, number]> {
  const sorted = [...zones].sort((a, b) => a.key.localeCompare(b.key));
  const out: Record<string, [number, number]> = {};
  const mPerDegLat = 111_320;
  const mPerDegLng = 111_320 * Math.cos((center[0] * Math.PI) / 180);
  const inner = Math.ceil(sorted.length / 2.6);
  sorted.forEach((z, i) => {
    const onInner = i < inner;
    const idx = onInner ? i : i - inner;
    const total = onInner ? inner : sorted.length - inner;
    const r = radiusM * (onInner ? 0.32 : 0.62);
    const ang = (2 * Math.PI * idx) / Math.max(total, 1) + (onInner ? 0 : Math.PI / total);
    out[z.key] = [center[0] + (r * Math.sin(ang)) / mPerDegLat, center[1] + (r * Math.cos(ang)) / mPerDegLng];
  });
  return out;
}

export function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

export function fmtMin(m: number | null | undefined): string {
  if (m === null || m === undefined) return "—";
  if (m >= 60) return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
  return `${m}m`;
}

export function fmtClock(iso: string | null | undefined): string {
  return iso
    ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })
    : "—";
}

export function todayIST(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export function FreshBadge({ w }: { w: Pick<Worker, "freshness" | "seconds_since"> }) {
  const { t } = useI18n();
  if (!w.freshness) return <Chip>—</Chip>;
  const tone = w.freshness === "live" ? "green" : w.freshness === "recent" ? "amber" : undefined;
  const label = t(`prs_${w.freshness}`);
  const mins = w.seconds_since !== null ? Math.round(w.seconds_since / 60) : null;
  return <Chip tone={tone}>{label}{mins !== null ? ` · ${mins}m` : ""}</Chip>;
}

const TABS: [string, string][] = [
  ["live", "/presence"],
  ["alerts", "/presence/alerts"],
  ["summary", "/presence/summary"],
  ["muster", "/presence/muster"],
];

/** Sub-navigation of the presence area with a live open-alert badge (30 s poll). */
export function PresenceTabs({ active }: { active: "live" | "alerts" | "summary" | "muster" }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const [openCount, setOpenCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api("/presence/alerts?status=open")
        .then((r) => { if (alive) setOpenCount(r.open_total || 0); })
        .catch(() => undefined);
    load();
    const t1 = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(t1); };
  }, []);
  return (
    <div className="tabs" data-testid="presence-tabs">
      {TABS.map(([k, to]) => (
        <button key={k} className={active === k ? "on" : ""} onClick={() => nav(to)} data-testid={`prs-tab-${k}`}>
          {t(`prs2_tab_${k}`)}
          {k === "alerts" && openCount > 0 ? <span className="tab-badge">{openCount}</span> : null}
        </button>
      ))}
    </div>
  );
}
