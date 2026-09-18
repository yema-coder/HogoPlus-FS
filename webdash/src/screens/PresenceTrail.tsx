import L from "leaflet";
import "leaflet/dist/leaflet.css";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Circle, MapContainer, Marker, Polyline, Popup, TileLayer } from "react-leaflet";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Loading } from "../components";
import { useI18n } from "../i18n";
import { PresenceTabs, fmtClock, fmtMin, todayIST, zoneName, zonePositions } from "../presence/shared";

/** v1.0.26 Phase 2 — one worker's day: vertical timeline of zone entries/exits
 * + animated map trail replay (play/pause slider). Beacon fixes carry no GPS,
 * so they animate at their zone's indicative ring position. */

interface Pt {
  ts: string; source: string; zone_key: string | null; zone_en: string | null;
  lat: number | null; lng: number | null; inside_geofence: boolean | null; battery_pct: number | null;
}
interface Seg {
  kind: string; zone_key: string | null; zone_en: string | null; zone_hi: string | null;
  zone_mr: string | null; from_ts: string; to_ts: string; minutes: number;
}
interface TL {
  generated_at: string; date: string;
  worker: { id: string; emp_id: string; full_name: string; department_code: string | null };
  punch_in_at: string | null; punch_out_at: string | null;
  geofence: { lat: number; lng: number; radius_m: number };
  points: Pt[]; segments: Seg[];
  zones: { key: string; name_en: string; name_hi: string; name_mr: string }[];
}

const PLAY_MS = 600;

export default function PresenceTrail() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const { t, lang } = useI18n();
  const [data, setData] = useState<TL | null>(null);
  const [error, setError] = useState("");
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<any>(null);
  const date = sp.get("date") || todayIST();

  useEffect(() => {
    setData(null);
    setIdx(0);
    setPlaying(false);
    api(`/presence/timeline?employee_id=${id}&date=${date}`)
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e.message));
  }, [id, date]);

  const center: [number, number] = data?.geofence ? [data.geofence.lat, data.geofence.lng] : [19.313483, 74.709384];
  const radiusM = data?.geofence?.radius_m || 1200;
  const zonePos = useMemo(
    () => zonePositions(data?.zones || [], center, radiusM),
    [data, center[0], center[1], radiusM]
  );

  /** points that can be drawn: GPS at real coords, beacon at its zone position */
  const plottable = useMemo(
    () =>
      (data?.points || []).flatMap((p) => {
        let pos: [number, number] | null = null;
        if (p.lat !== null && p.lng !== null) pos = [p.lat, p.lng];
        else if (p.zone_key && zonePos[p.zone_key]) pos = zonePos[p.zone_key];
        return pos ? [{ p, pos }] : [];
      }),
    [data, zonePos]
  );

  useEffect(() => {
    if (!playing) return;
    timer.current = setInterval(() => {
      setIdx((i) => {
        if (i + 1 >= plottable.length) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, PLAY_MS);
    return () => clearInterval(timer.current);
  }, [playing, plottable.length]);

  const segLabel = (s: Seg): string => {
    if (s.kind === "zone") return zoneName({ name_en: s.zone_en, name_hi: s.zone_hi, name_mr: s.zone_mr }, lang);
    return t(`prs2_seg_${s.kind}`);
  };

  if (error && !data) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!data) return <Loading />;

  const cur = plottable[Math.min(idx, Math.max(0, plottable.length - 1))];
  const path = plottable.slice(0, idx + 1).map((x) => x.pos);

  return (
    <>
      <div className="topbar">
        <h1 data-testid="trail-title">
          <button className="btn ghost" style={{ padding: "4px 10px", marginRight: 8 }} onClick={() => nav(-1)}
                  data-testid="trail-back">{t("prs2_back_to_summary")}</button>
          👣 {data.worker.full_name}
          <span style={{ fontSize: 14, color: "var(--muted)", fontWeight: 600 }}> {data.worker.emp_id} · {data.worker.department_code || "—"}</span>
        </h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600 }}>
            {t("prs2_punch")}: {fmtClock(data.punch_in_at)} → {data.punch_out_at ? fmtClock(data.punch_out_at) : "…"}
          </span>
          <input type="date" value={date} max={todayIST()} data-testid="trail-date"
                 onChange={(e) => e.target.value && setSp({ date: e.target.value })} />
        </div>
      </div>
      <PresenceTabs active="summary" />

      {data.points.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--muted)", fontWeight: 600 }}
             data-testid="trail-empty">
          {t("prs2_no_points")}
        </div>
      ) : (
        <div className="tl-wrap">
          <div className="card" data-testid="trail-timeline">
            <h2>🕐 {t("prs2_timeline")}</h2>
            {data.segments.map((s, i) => (
              <div key={i} className={`tl-seg ${s.kind}`} data-testid={`tl-seg-${i}`}>
                <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>
                  {fmtClock(s.from_ts)} – {fmtClock(s.to_ts)} · {fmtMin(s.minutes)}
                </div>
                <div style={{ fontWeight: 800, fontSize: 14 }}>{segLabel(s)}</div>
              </div>
            ))}
          </div>

          <div className="card" data-testid="trail-map" style={{ padding: 10 }}>
            <div className="prs-map-wrap">
              <MapContainer center={center} zoom={15} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <Circle center={center} radius={radiusM}
                        pathOptions={{ color: "#0B4F6C", fillColor: "#0B4F6C", fillOpacity: 0.06, weight: 2, dashArray: "6 6" }} />
                {data.zones.map((z) => zonePos[z.key] && (
                  <Marker key={z.key} position={zonePos[z.key]}
                          icon={L.divIcon({ className: "", html: `<div class="zone-pin"><span>·</span></div>`,
                                            iconSize: [30, 30], iconAnchor: [15, 15] })}>
                    <Popup><b>{zoneName(z, lang)}</b></Popup>
                  </Marker>
                ))}
                {/* full faint trail + progressed bold trail */}
                <Polyline positions={plottable.map((x) => x.pos)}
                          pathOptions={{ color: "#9CA3AF", weight: 2, dashArray: "4 6", opacity: 0.7 }} />
                {path.length > 1 && (
                  <Polyline positions={path} pathOptions={{ color: "#E8871E", weight: 4, opacity: 0.9 }} />
                )}
                {cur && (
                  <Marker position={cur.pos}
                          icon={L.divIcon({ className: "", html: `<div class="trail-current"></div>`,
                                            iconSize: [20, 20], iconAnchor: [10, 10] })} />
                )}
              </MapContainer>
            </div>
            <div className="play-row" data-testid="trail-controls">
              <button className="btn primary" style={{ padding: "6px 14px" }} data-testid="trail-play"
                      onClick={() => setPlaying(!playing)} disabled={plottable.length < 2}>
                {playing ? t("prs2_pause") : t("prs2_play")}
              </button>
              <input type="range" min={0} max={Math.max(0, plottable.length - 1)} value={idx}
                     data-testid="trail-slider"
                     onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} />
              <span style={{ fontSize: 13, fontWeight: 700, whiteSpace: "nowrap" }} data-testid="trail-cursor">
                {cur ? fmtClock(cur.p.ts) : "—"}
                {cur?.p.zone_en ? ` · ${cur.p.zone_en}` : cur?.p.source === "gps" ? " · GPS" : ""}
                {cur?.p.battery_pct !== null && cur?.p.battery_pct !== undefined ? ` · 🔋${cur.p.battery_pct}%` : ""}
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
