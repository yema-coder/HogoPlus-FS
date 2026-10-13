import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useI18n } from "./i18n";

/* Mappls (MapmyIndia) Web Map SDK wrapper.
 *
 * - Token comes from the backend (`/dashboard/maps-token`); the CLIENT_SECRET never
 *   reaches the browser, only a short-lived OAuth token.
 * - Default style is satellite/hybrid ("standard-hybrid") per the owner mandate.
 * - Draws the exact pin, a GPS-accuracy circle, and the factory geofence circle.
 * - Fails SOFT: if Mappls is unconfigured / the SDK can't load, we render a clean
 *   coordinates + "Open in Maps" fallback instead of a broken map.
 */

type MapsConfig = {
  configured: boolean;
  token: string | null;
  factory: { lat: number | null; lng: number | null; radius_m: number | null } | null;
};

let _configPromise: Promise<MapsConfig> | null = null;
function getMapsConfig(): Promise<MapsConfig> {
  if (!_configPromise) {
    _configPromise = api("/dashboard/maps-token").catch(
      () => ({ configured: false, token: null, factory: null }) as MapsConfig,
    );
  }
  return _configPromise;
}

let _sdkPromise: Promise<boolean> | null = null;
function loadSdk(token: string): Promise<boolean> {
  if (_sdkPromise) return _sdkPromise;
  _sdkPromise = new Promise<boolean>((resolve) => {
    const w = window as any;
    if (w.mappls?.Map) return resolve(true);
    const s = document.createElement("script");
    s.src = `https://apis.mappls.com/advancedmaps/api/${token}/map_sdk?layer=vector&v=3.0`;
    s.async = true;
    s.onload = () => resolve(!!(window as any).mappls?.Map);
    s.onerror = () => resolve(false);
    document.head.appendChild(s);
    setTimeout(() => resolve(!!(window as any).mappls?.Map), 9000);
  });
  return _sdkPromise;
}

function mapplsUrl(lat: number, lng: number) {
  return `https://maps.mappls.com/@${lat},${lng},17z`;
}

function Fallback({ lat, lng }: { lat: number; lng: number }) {
  const { t } = useI18n();
  return (
    <div className="map-fallback" data-testid="map-fallback">
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 6 }}>{t("mapUnavailable")}</div>
      <div style={{ fontFamily: "monospace", fontSize: 14 }}>{lat.toFixed(5)}, {lng.toFixed(5)}</div>
      <a className="btn" style={{ marginTop: 8, display: "inline-block" }} href={mapplsUrl(lat, lng)} target="_blank" rel="noreferrer">
        {t("openInMaps")}
      </a>
    </div>
  );
}

export default function MapplsMap({
  lat,
  lng,
  accuracy,
  zoom = 16,
  height = 260,
  geofence = true,
}: {
  lat: number;
  lng: number;
  accuracy?: number | null;
  zoom?: number;
  height?: number;
  geofence?: boolean;
}) {
  const idRef = useRef(`mappls_${Math.random().toString(36).slice(2)}`);
  const mapRef = useRef<any>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">("loading");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cfg = await getMapsConfig();
      if (cancelled) return;
      if (!cfg?.configured || !cfg.token) return setStatus("fallback");
      const ok = await loadSdk(cfg.token);
      if (cancelled) return;
      const mappls = (window as any).mappls;
      if (!ok || !mappls?.Map) return setStatus("fallback");
      try {
        const map = new mappls.Map(idRef.current, { center: [lat, lng], zoom, zoomControl: true });
        mapRef.current = map;
        let done = false;
        const setup = () => {
          if (done || cancelled) return;
          done = true;
          try { map.setStyle("standard-hybrid"); } catch { /* keep default tiles */ }
          try { new mappls.Marker({ map, position: { lat, lng } }); } catch { /* pin optional */ }
          if (accuracy && accuracy > 0) {
            try {
              new mappls.Circle({
                map, center: { lat, lng }, radius: accuracy,
                strokeColor: "#2563eb", strokeWeight: 1, strokeOpacity: 0.6,
                fillColor: "#3b82f6", fillOpacity: 0.15,
              });
            } catch { /* circle optional */ }
          }
          const f = cfg.factory;
          if (geofence && f && f.lat != null && f.lng != null) {
            try {
              new mappls.Circle({
                map, center: { lat: f.lat, lng: f.lng }, radius: f.radius_m || 1200,
                strokeColor: "#16a34a", strokeWeight: 1, strokeOpacity: 0.7,
                fillColor: "#22c55e", fillOpacity: 0.05,
              });
            } catch { /* geofence optional */ }
          }
          if (!cancelled) setStatus("ready");
        };
        try { map.on("load", setup); } catch { /* fall through to timer */ }
        setTimeout(setup, 1800);
      } catch {
        setStatus("fallback");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setStyle = (s: string) => { try { mapRef.current?.setStyle(s); } catch { /* ignore */ } };
  const recenter = () => {
    const m = mapRef.current;
    if (!m) return;
    try { m.setCenter?.({ lat, lng }); } catch { /* ignore */ }
    try { m.setZoom?.(zoom); } catch { /* ignore */ }
    try { m.flyTo?.({ center: [lat, lng], zoom }); } catch { /* ignore */ }
  };

  if (status === "fallback") return <Fallback lat={lat} lng={lng} />;

  return (
    <div style={{ position: "relative" }} data-testid="mappls-map">
      <div id={idRef.current} style={{ height, width: "100%", borderRadius: 8, overflow: "hidden", background: "#e5e7eb" }} />
      {status === "ready" && (
        <div style={{ position: "absolute", top: 8, left: 8, display: "flex", gap: 6, zIndex: 5 }}>
          <button className="btn sm" onClick={() => setStyle("standard-hybrid")}>🛰</button>
          <button className="btn sm" onClick={() => setStyle("standard-day")}>🗺</button>
          <button className="btn sm" onClick={recenter}>⌖</button>
        </div>
      )}
    </div>
  );
}
