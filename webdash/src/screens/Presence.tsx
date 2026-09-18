import L from "leaflet";
import "leaflet/dist/leaflet.css";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Circle, MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import { api } from "../api";
import { isTopMgmt, useAuth } from "../auth";
import { Chip, Loading } from "../components";
import { useI18n } from "../i18n";

/** v1.0.25 LIVE WORKER PRESENCE — Phase 1 dashboard.
 * Freshness (server receive time): Live <=6 min · Recent <=15 min · Stale >15 min.
 * Auto-refreshes every 15 s without a page reload. Works down to 360 px. */

const REFRESH_MS = 15_000;

interface Zone { key: string; name_en: string; name_hi: string; name_mr: string; count: number }
interface Worker {
  id: string; emp_id: string; full_name: string; department_code: string | null;
  status: string; freshness: string | null; seconds_since: number | null;
  zone_key: string | null; zone_en: string | null; zone_hi: string | null; zone_mr: string | null;
  lat: number | null; lng: number | null; inside_geofence: boolean | null;
  battery_pct: number | null; last_seen: string | null; punched_in_at: string;
}
interface Snapshot {
  enabled: boolean; generated_at: string; scope?: string;
  geofence?: { lat: number; lng: number; radius_m: number };
  counts?: Record<string, number>; zones?: Zone[]; workers?: Worker[];
}

const STATUS_TONE: Record<string, "green" | "red" | "amber" | "blue" | undefined> = {
  in_zone: "green", gps_inside: "green", gps_outside: "red",
  stopped: "amber", no_signal: undefined, not_tracked: undefined,
};

function zoneName(z: { name_en?: string | null; zone_en?: string | null; [k: string]: any }, lang: string): string {
  return z[`name_${lang}`] || z[`zone_${lang}`] || z.name_en || z.zone_en || "—";
}

/** Beacons carry no GPS coordinates (indoor). Zones get a stable, deterministic
 * ring layout inside the geofence so counts are glanceable on the map. */
function zonePositions(zones: Zone[], center: [number, number], radiusM: number): Record<string, [number, number]> {
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

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

function FreshBadge({ w }: { w: Worker }) {
  const { t } = useI18n();
  if (!w.freshness) return <Chip>—</Chip>;
  const tone = w.freshness === "live" ? "green" : w.freshness === "recent" ? "amber" : undefined;
  const label = t(`prs_${w.freshness}`);
  const mins = w.seconds_since !== null ? Math.round(w.seconds_since / 60) : null;
  return <Chip tone={tone}>{label}{mins !== null ? ` · ${mins}m` : ""}</Chip>;
}

export default function Presence() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [lastFetch, setLastFetch] = useState<number | null>(null);
  const [, tick] = useState(0);
  // filters
  const [statusFilter, setStatusFilter] = useState("");
  const [deptFilter, setDeptFilter] = useState("");
  const [zoneFilter, setZoneFilter] = useState("");
  const [q, setQ] = useState("");
  const [zoneQ, setZoneQ] = useState("");
  const [hideEmpty, setHideEmpty] = useState(false);
  const [outsideFirst, setOutsideFirst] = useState(true);
  const [enabling, setEnabling] = useState(false);
  const timer = useRef<any>(null);

  const load = async () => {
    try {
      const s = await api("/presence/live");
      setSnap(s);
      setError("");
      setLastFetch(Date.now());
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
    timer.current = setInterval(load, REFRESH_MS);
    const t1 = setInterval(() => tick((x) => x + 1), 1000);
    return () => { clearInterval(timer.current); clearInterval(t1); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const enableNow = async () => {
    setEnabling(true);
    try {
      await api("/presence/settings", { method: "PUT", body: JSON.stringify({ live_presence_enabled: true }) });
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setEnabling(false);
    }
  };

  const zones = snap?.zones || [];
  const workers = snap?.workers || [];
  const counts = snap?.counts || ({} as Record<string, number>);
  const center: [number, number] = snap?.geofence ? [snap.geofence.lat, snap.geofence.lng] : [19.313483, 74.709384];
  const radiusM = snap?.geofence?.radius_m || 1200;
  const zonePos = useMemo(() => zonePositions(zones, center, radiusM), [zones, center[0], center[1], radiusM]);

  const depts = useMemo(
    () => Array.from(new Set(workers.map((w) => w.department_code).filter(Boolean) as string[])).sort(),
    [workers]
  );

  const shownZones = useMemo(() => {
    let zs = zones;
    if (hideEmpty) zs = zs.filter((z) => z.count > 0);
    const needle = zoneQ.trim().toLowerCase();
    if (needle) zs = zs.filter((z) => `${z.name_en} ${z.name_hi} ${z.name_mr}`.toLowerCase().includes(needle));
    return [...zs].sort((a, b) => b.count - a.count || a.name_en.localeCompare(b.name_en));
  }, [zones, hideEmpty, zoneQ]);

  const OUTSIDE_ORDER: Record<string, number> = { gps_outside: 0, stopped: 1, no_signal: 2 };
  const shownWorkers = useMemo(() => {
    let ws = workers;
    if (statusFilter) ws = ws.filter((w) => w.status === statusFilter);
    if (deptFilter) ws = ws.filter((w) => w.department_code === deptFilter);
    if (zoneFilter) ws = ws.filter((w) => w.zone_key === zoneFilter);
    const needle = q.trim().toLowerCase();
    if (needle) ws = ws.filter((w) => `${w.full_name} ${w.emp_id}`.toLowerCase().includes(needle));
    return [...ws].sort((a, b) => {
      if (outsideFirst) {
        const oa = OUTSIDE_ORDER[a.status] ?? 9, ob = OUTSIDE_ORDER[b.status] ?? 9;
        if (oa !== ob) return oa - ob;
      }
      return a.full_name.localeCompare(b.full_name);
    });
  }, [workers, statusFilter, deptFilter, zoneFilter, q, outsideFirst]);

  /** map dot: gps workers at real coords; beacon workers jittered around their
   * zone marker; grey when stale/stopped. Workers without any position are skipped. */
  const dots = useMemo(() => {
    return workers.flatMap((w) => {
      let pos: [number, number] | null = null;
      if (w.lat !== null && w.lng !== null) pos = [w.lat, w.lng];
      else if (w.zone_key && zonePos[w.zone_key]) {
        const h = hash(w.emp_id);
        const ang = (h % 360) * (Math.PI / 180);
        const r = 20 + (h % 45);
        pos = [zonePos[w.zone_key][0] + (r * Math.sin(ang)) / 111_320,
               zonePos[w.zone_key][1] + (r * Math.cos(ang)) / (111_320 * Math.cos((center[0] * Math.PI) / 180))];
      }
      if (!pos) return [];
      const color =
        w.status === "gps_outside" ? "#E85A6F"
        : w.status === "in_zone" || w.status === "gps_inside" ? "#22C55E"
        : "#9CA3AF"; // no_signal / stopped / not_tracked = grey
      return [{ w, pos, color }];
    });
  }, [workers, zonePos]);

  if (error && !snap) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!snap) return <Loading />;

  if (!snap.enabled) {
    return (
      <>
        <div className="topbar"><h1 data-testid="presence-title">📍 {t("prs_title")}</h1></div>
        <div className="card" data-testid="presence-disabled" style={{ textAlign: "center", padding: 40 }}>
          <h2>{t("prs_disabled_title")}</h2>
          <p style={{ color: "var(--muted)", margin: "10px 0 18px" }}>{t("prs_disabled_msg")}</p>
          {isTopMgmt(user) && (
            <button className="btn primary" data-testid="presence-enable" disabled={enabling} onClick={enableNow}>
              {t("prs_enable_now")}
            </button>
          )}
        </div>
      </>
    );
  }

  const ago = lastFetch ? Math.max(0, Math.round((Date.now() - lastFetch) / 1000)) : null;
  const kpis: [string, string, boolean?][] = [
    ["in_zone", "prs_in_zone"], ["gps_inside", "prs_gps_inside"], ["gps_outside", "prs_gps_outside", true],
    ["no_signal", "prs_no_signal"], ["not_tracked", "prs_not_tracked"], ["stopped", "prs_stopped", true],
  ];

  return (
    <>
      <div className="topbar">
        <h1 data-testid="presence-title">📍 {t("prs_title")}</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {snap.scope && snap.scope !== "all" && <Chip tone="blue">{t("department")}: {snap.scope}</Chip>}
          <span data-testid="presence-updated" style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600 }}>
            {t("prs_updated")} {ago}s
          </span>
          <button className="btn ghost" style={{ padding: "6px 12px" }} onClick={load}>↻ {t("refresh")}</button>
        </div>
      </div>

      {/* top strip */}
      <div className="prs-strip" data-testid="presence-strip">
        <div className="kpi big">
          <div className="v">{counts.tracking ?? 0} <span style={{ fontSize: 16, color: "var(--muted)" }}>/ {counts.on_shift ?? 0}</span></div>
          <div className="l">{t("prs_tracking_of")}</div>
        </div>
        {kpis.map(([key, label, red]) => (
          <div key={key} className={`kpi ${statusFilter === key ? "sel" : ""}`} data-testid={`kpi-${key}`}
               onClick={() => setStatusFilter(statusFilter === key ? "" : key)}>
            <div className={`v ${red && (counts[key] ?? 0) > 0 ? "red" : ""}`}>{counts[key] ?? 0}</div>
            <div className="l">{t(label)}</div>
          </div>
        ))}
      </div>
      <div className="prs-legend">
        <span><i className="dot g" /> {t("prs_live")} ≤6 min</span>
        <span><i className="dot a" /> {t("prs_recent")} ≤15 min</span>
        <span><i className="dot x" /> {t("prs_stale")} &gt;15 min</span>
      </div>

      <div className="prs-cols">
        {/* zone board */}
        <div className="card" data-testid="zone-board">
          <h2>🏭 {t("prs_zones")} ({zones.length})</h2>
          <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
            <input placeholder={t("prs_zone_search")} value={zoneQ} onChange={(e) => setZoneQ(e.target.value)}
                   style={{ flex: 1, minWidth: 140 }} data-testid="zone-search" />
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600 }}>
              <input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} data-testid="hide-empty" />
              {t("prs_hide_empty")}
            </label>
          </div>
          <div className="zone-grid">
            {shownZones.map((z) => (
              <div key={z.key} className={`zone-tile ${z.count > 0 ? "busy" : ""} ${zoneFilter === z.key ? "sel" : ""}`}
                   onClick={() => setZoneFilter(zoneFilter === z.key ? "" : z.key)}>
                <b>{zoneName(z, lang)}</b>
                {lang !== "mr" && z.name_mr && <div className="sub">{z.name_mr}</div>}
                {lang === "mr" && <div className="sub">{z.name_en}</div>}
                <span className="cnt">{z.count}</span>
              </div>
            ))}
            {shownZones.length === 0 && <div style={{ color: "var(--muted)", padding: 10 }}>{t("noData")}</div>}
          </div>
        </div>

        {/* map */}
        <div className="card" data-testid="presence-map" style={{ padding: 10 }}>
          <h2 style={{ padding: "6px 8px 0" }}>🗺️ {t("prs_map")}</h2>
          <div className="prs-map-wrap">
            <MapContainer center={center} zoom={15} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <Circle center={center} radius={radiusM}
                      pathOptions={{ color: "#0B4F6C", fillColor: "#0B4F6C", fillOpacity: 0.06, weight: 2, dashArray: "6 6" }} />
              {zones.map((z) => zonePos[z.key] && (
                <Marker key={z.key} position={zonePos[z.key]}
                        icon={L.divIcon({ className: "", html:
                          `<div class="zone-pin ${z.count > 0 ? "busy" : ""}"><span>${z.count}</span></div>`,
                          iconSize: [30, 30], iconAnchor: [15, 15] })}>
                  <Popup><b>{zoneName(z, lang)}</b><br />{z.count} {t("prs_workers_short")}</Popup>
                </Marker>
              ))}
              <MarkerClusterGroup chunkedLoading maxClusterRadius={36}
                iconCreateFunction={(cluster: any) =>
                  L.divIcon({ className: "", html: `<div class="dot-cluster">${cluster.getChildCount()}</div>`,
                              iconSize: [34, 34], iconAnchor: [17, 17] })}>
                {dots.map(({ w, pos, color }) => (
                  <Marker key={w.id} position={pos}
                          icon={L.divIcon({ className: "", html:
                            `<div class="worker-dot" style="background:${color}"></div>`,
                            iconSize: [16, 16], iconAnchor: [8, 8] })}>
                    <Popup>
                      <b>{w.full_name}</b> ({w.emp_id})<br />
                      {t(`prs_${w.status}`)}{w.zone_en ? ` · ${zoneName(w, lang)}` : ""}<br />
                      {w.freshness ? `${t(`prs_${w.freshness}`)} · ` : ""}{w.battery_pct !== null ? `🔋${w.battery_pct}%` : ""}
                    </Popup>
                  </Marker>
                ))}
              </MarkerClusterGroup>
            </MapContainer>
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", padding: "6px 8px 2px" }}>{t("prs_zone_positions_note")}</div>
        </div>
      </div>

      {/* worker list */}
      <div className="card" data-testid="worker-list">
        <h2>👷 {t("prs_worker_list")} ({shownWorkers.length})</h2>
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <input placeholder={t("prs_search")} value={q} onChange={(e) => setQ(e.target.value)}
                 style={{ flex: 2, minWidth: 150 }} data-testid="worker-search" />
          <select value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)} data-testid="dept-filter">
            <option value="">{t("prs_all_depts")}</option>
            {depts.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <select value={zoneFilter} onChange={(e) => setZoneFilter(e.target.value)} data-testid="zone-filter">
            <option value="">{t("prs_all_zones")}</option>
            {zones.map((z) => <option key={z.key} value={z.key}>{zoneName(z, lang)}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} data-testid="status-filter">
            <option value="">{t("prs_all_status")}</option>
            {["in_zone", "gps_inside", "gps_outside", "no_signal", "stopped", "not_tracked"].map((s) => (
              <option key={s} value={s}>{t(`prs_${s}`)}</option>
            ))}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600 }}>
            <input type="checkbox" checked={outsideFirst} onChange={(e) => setOutsideFirst(e.target.checked)} data-testid="outside-first" />
            {t("prs_outside_first")}
          </label>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr>
              <th>{t("name")}</th><th>{t("department")}</th><th>{t("status")}</th>
              <th>{t("prs_zone")}</th><th>{t("prs_freshness")}</th><th>{t("prs_last_seen")}</th><th>🔋</th>
            </tr></thead>
            <tbody>
              {shownWorkers.map((w) => (
                <tr key={w.id} className={w.status === "gps_outside" ? "red" : ""} data-testid={`worker-row-${w.emp_id}`}>
                  <td><b>{w.full_name}</b> <span style={{ color: "var(--muted)", fontSize: 12 }}>{w.emp_id}</span></td>
                  <td>{w.department_code || "—"}</td>
                  <td><Chip tone={STATUS_TONE[w.status]}>{t(`prs_${w.status}`)}</Chip></td>
                  <td>{w.zone_en ? zoneName(w, lang) : w.status.startsWith("gps") ? "GPS" : "—"}</td>
                  <td><FreshBadge w={w} /></td>
                  <td style={{ whiteSpace: "nowrap" }}>{w.last_seen ? new Date(w.last_seen).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) : "—"}</td>
                  <td>{w.battery_pct !== null ? `${w.battery_pct}%` : "—"}</td>
                </tr>
              ))}
              {shownWorkers.length === 0 && <tr><td colSpan={7} style={{ textAlign: "center", color: "var(--muted)" }}>{t("noData")}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
