import React, { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { AgeChip, Chip } from "../components";
import { useI18n } from "../i18n";
import { useCachedApi } from "../swr";

const PAGE = 20;
const t0 = performance.now();
let firstPaintLogged = false;

function SkeletonRow() {
  return (
    <div className="feed-item">
      <div className="skel" style={{ width: 64, height: 64, borderRadius: 10 }} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="skel" style={{ height: 16, width: "60%" }} />
        <div className="skel" style={{ height: 12, width: "40%" }} />
      </div>
    </div>
  );
}

function Thumb({ i, size = 64 }: { i: any; size?: number }) {
  const style: React.CSSProperties = { width: size, height: size, borderRadius: 10, objectFit: "cover", background: "var(--bg)" };
  if (i.video_url) return <video src={i.video_url} style={style} muted preload="none" />;
  if (i.photo_url) return <img src={i.photo_url} alt="" loading="lazy" style={style} />;
  return <div style={{ ...style, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }}>⚠️</div>;
}

function DetailModal({ item, onClose }: { item: any; onClose: () => void }) {
  const { t } = useI18n();
  const [analysis, setAnalysis] = useState<any | null>(null);
  const [blur, setBlur] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [saving, setSaving] = useState(false);
  const [plate, setPlate] = useState<string | null>(item.detected_plate ?? null);

  const loadAnalysis = () =>
    api(`/incidents/${item.id}/analysis`).then(setAnalysis).catch(() => setAnalysis(null));
  useEffect(() => {
    void loadAnalysis();
  }, [item.id]);

  const primary =
    analysis?.photos?.find((p: any) => p.slot === "primary") ?? analysis?.photos?.[0] ?? null;
  const faces: any[] = primary?.faces ?? [];
  const plates: any[] = primary?.plates ?? [];
  const ps = analysis?.plate_scale;

  const savePlate = async () => {
    if (!editId || !editText.trim()) return;
    setSaving(true);
    try {
      await api(`/incidents/${item.id}/plates/${editId}`, {
        method: "PATCH",
        body: JSON.stringify({ text: editText.trim().toUpperCase() }),
      });
      setPlate(editText.trim().toUpperCase());
      setEditId(null);
      await loadAnalysis();
    } catch {
      /* keep editor open on failure */
    } finally {
      setSaving(false);
    }
  };

  const pct = (v: number) => `${v * 100}%`;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" data-testid="incident-detail-modal" onClick={(e) => e.stopPropagation()}>
        {item.video_url ? (
          <video src={item.video_url} controls style={{ width: "100%", borderRadius: 12, maxHeight: 320, background: "#000" }} />
        ) : item.photo_url ? (
          <div style={{ position: "relative", width: "100%", borderRadius: 12, overflow: "hidden", background: "#000" }}>
            <img src={item.photo_url} alt="" style={{ width: "100%", display: "block" }} />
            {plates.map((p) => (
              <div
                key={p.id}
                data-testid={`dash-plate-box-${p.id}`}
                onClick={() => {
                  setEditId(p.id);
                  setEditText(p.text ?? "");
                }}
                title={t("an_edit_plate")}
                style={{
                  position: "absolute", left: pct(p.x), top: pct(p.y), width: pct(p.w), height: pct(p.h),
                  border: "2.5px solid var(--accent)", borderRadius: 4, cursor: "pointer", boxSizing: "border-box",
                }}
              >
                <span style={{
                  position: "absolute", top: -20, left: -2, background: "var(--accent)", color: "#fff",
                  fontSize: 11, fontWeight: 800, padding: "1px 6px", borderRadius: 6, whiteSpace: "nowrap",
                }}>{p.text || "?"} ✎</span>
              </div>
            ))}
            {faces.map((f) => (
              <div
                key={f.id}
                data-testid={`dash-face-box-${f.id}`}
                style={{
                  position: "absolute", left: pct(f.x), top: pct(f.y), width: pct(f.w), height: pct(f.h),
                  boxSizing: "border-box", borderRadius: 8,
                  ...(blur
                    ? { background: "rgba(190,195,205,0.45)", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)", border: "1.5px solid #6B7280" }
                    : { border: "2px solid var(--warning, #F59E0B)" }),
                }}
              />
            ))}
          </div>
        ) : null}

        {/* analysis controls */}
        {item.photo_url ? (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            {faces.length ? (
              <button
                className="btn"
                data-testid="dash-blur-toggle"
                onClick={() => setBlur((v) => !v)}
                style={blur ? { background: "var(--accent)", color: "#fff" } : undefined}
              >
                🙈 {blur ? t("an_blur_on") : t("an_blur")} ({faces.length})
              </button>
            ) : null}
            {analysis?.pending ? <Chip tone="amber">⏳ {t("an_pending")}</Chip> : null}
          </div>
        ) : null}

        {editId ? (
          <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
            <input
              data-testid="dash-plate-input"
              value={editText}
              onChange={(e) => setEditText(e.target.value.toUpperCase())}
              maxLength={20}
              placeholder="MH12AB1234"
              style={{ flex: 1, letterSpacing: 2, fontWeight: 700 }}
            />
            <button className="btn primary" data-testid="dash-plate-save" disabled={saving} onClick={savePlate}>{t("save")}</button>
            <button className="btn" onClick={() => setEditId(null)}>{t("back")}</button>
          </div>
        ) : plates.length ? (
          <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 0" }}>{t("an_tap_plate")}</p>
        ) : null}

        <h2 style={{ marginTop: 10 }}>{item.category} · {item.department_code}</h2>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0" }}>
          <Chip tone={item.severity === "critical" ? "red" : item.severity === "high" ? "amber" : undefined}>{item.severity}</Chip>
          <Chip tone="blue">{item.status}</Chip>
          <AgeChip hours={item.age_hours} />
          {plate ? <Chip tone="green">🚗 {plate}</Chip> : null}
          {faces.length ? <Chip tone="blue">🙂 {faces.length} {t("an_faces")}</Chip> : null}
        </div>
        <div className="detail-rows">
          <div><b>{t("reporter")}:</b> {item.reporter_name}</div>
          {item.description ? <div><b>{t("description")}:</b> {item.description}</div> : null}
          {analysis?.distance?.distance_m != null ? (
            <div data-testid="dash-distance">
              <b>📏 {t("an_distance")}:</b> {analysis.distance.distance_m.toFixed(1)} m
              {analysis.distance.distance_uncertainty_m ? ` ±${analysis.distance.distance_uncertainty_m.toFixed(1)}` : ""}
              {analysis.distance.distance_method ? ` · ${analysis.distance.distance_method}` : ""}
            </div>
          ) : null}
          {ps ? (
            <div data-testid="dash-crosscheck">
              <b>🧮 {t("an_crosscheck")}:</b> ~{ps.est_distance_m.toFixed(1)} m
              {ps.consistent != null ? (
                <span style={{
                  marginLeft: 6, fontSize: 11, fontWeight: 800, padding: "1px 8px", borderRadius: 10, color: "#fff",
                  background: ps.consistent ? "var(--success, #1E8E4E)" : "var(--danger, #D64545)",
                }}>{ps.consistent ? `✓ ${t("an_consistent")}` : `⚠ ${t("an_mismatch")} (${ps.delta_pct}%)`}</span>
              ) : null}
            </div>
          ) : null}
          {item.ble_zone ? <div><b>📍 {t("beaconZone")}:</b> {item.ble_zone}</div>
            : item.address_text ? <div><b>📍</b> {item.address_text}</div>
            : (item.gps_lat != null && item.gps_lng != null) ? <div><b>📍</b> {item.gps_lat.toFixed(5)}, {item.gps_lng.toFixed(5)}</div>
            : null}
          {item.voice_note_url ? <audio src={item.voice_note_url} controls style={{ width: "100%", marginTop: 6 }} /> : null}
          <div style={{ color: "var(--muted)" }}>{new Date(item.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</div>
        </div>
        <button className="btn primary" style={{ marginTop: 12, width: "100%" }} onClick={onClose}>{t("back")}</button>
      </div>
    </div>
  );
}

/** Prompt 18: the DEFAULT landing view — newest + open-critical complaints first,
 * photo thumbnails, severity chips, plate filter, first 20 + infinite scroll. */
export default function Incidents() {
  const { t } = useI18n();
  const { data, loading, error, refresh } = useCachedApi<any>("feed0", `/dashboard/incidents-feed?limit=${PAGE}`);
  const [extra, setExtra] = useState<any[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [busyMore, setBusyMore] = useState(false);
  const [q, setQ] = useState("");
  const [serverResults, setServerResults] = useState<any[] | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (data && !firstPaintLogged) {
      firstPaintLogged = true;
      console.info(`[perf] incidents first data render: ${Math.round(performance.now() - t0)}ms since bundle start`);
    }
    if (data) setHasMore(Boolean(data.has_more));
  }, [data]);

  // server-side search (covers full history incl. plates), debounced
  useEffect(() => {
    const query = q.trim();
    if (query.length < 2) {
      setServerResults(null);
      return;
    }
    const id = setTimeout(() => {
      api(`/dashboard/incidents-feed?limit=50&q=${encodeURIComponent(query)}`)
        .then((r: any) => setServerResults(r.items))
        .catch(() => setServerResults([]));
    }, 350);
    return () => clearTimeout(id);
  }, [q]);

  const baseItems: any[] = data?.items ?? [];
  const seen = new Set(baseItems.map((i) => i.id));
  const items = serverResults ?? [...baseItems, ...extra.filter((i) => !seen.has(i.id))];

  const loadMore = async () => {
    if (busyMore || !hasMore || serverResults) return;
    setBusyMore(true);
    try {
      const offset = baseItems.length + extra.length;
      const r: any = await api(`/dashboard/incidents-feed?limit=${PAGE}&offset=${offset}`);
      setExtra((prev) => [...prev, ...r.items]);
      setHasMore(Boolean(r.has_more));
    } catch {
      /* keep the button visible for retry */
    } finally {
      setBusyMore(false);
    }
  };

  // infinite scroll
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const obs = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) void loadMore();
    });
    obs.observe(el);
    return () => obs.disconnect();
  });

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="incidents-title">{t("nav_incidents")}</h1>
        <button className="btn ghost" onClick={() => { setExtra([]); refresh(); }}>↻ {t("refresh")}</button>
      </div>

      <input
        data-testid="incident-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t("searchIncidents")}
        style={{ width: "100%", marginBottom: 14 }}
      />

      {error && !items.length ? <div className="card" style={{ color: "var(--danger)" }}>{error}</div> : null}

      <div className="card" data-testid="incident-feed">
        {loading && !items.length ? (
          <>{[1, 2, 3, 4, 5].map((n) => <SkeletonRow key={n} />)}</>
        ) : items.length === 0 ? (
          <div style={{ color: "var(--muted)", padding: 12 }}>{t("noData")}</div>
        ) : (
          items.map((i: any) => (
            <div key={i.id} className="feed-item big" data-testid={`incident-row-${i.id}`} onClick={() => setDetail(i)}>
              <Thumb i={i} />
              <div style={{ flex: 1 }}>
                <div className="t">{i.category} · {i.department_code}{i.video_url ? " · 🎬" : ""}</div>
                <div className="m">{i.reporter_name} · {i.status}{i.detected_plate ? <> · <b style={{ color: "var(--accent)" }}>🚗 {i.detected_plate}</b></> : null}</div>
                {i.ble_zone ? <div className="m">📍 {i.ble_zone}</div>
                  : i.address_text ? <div className="m">📍 {i.address_text}</div> : null}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
                <Chip tone={i.severity === "critical" ? "red" : i.severity === "high" ? "amber" : undefined}>{i.severity}</Chip>
                <AgeChip hours={i.age_hours} />
              </div>
            </div>
          ))
        )}
        {!serverResults && hasMore && items.length > 0 ? (
          <div ref={sentinel} style={{ textAlign: "center", padding: 10 }}>
            <button className="btn ghost" data-testid="load-more" disabled={busyMore} onClick={loadMore}>
              {busyMore ? "…" : t("loadMore")}
            </button>
          </div>
        ) : null}
      </div>

      {detail ? <DetailModal item={detail} onClose={() => setDetail(null)} /> : null}
    </div>
  );
}
