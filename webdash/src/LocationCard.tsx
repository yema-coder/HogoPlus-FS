import React, { useState } from "react";
import { Chip } from "./components";
import { useI18n } from "./i18n";
import MapplsMap from "./MapplsMap";

/* Universal location card for an attendance punch (or any record carrying a GPS fix).
 * Accepts the raw attendance row shape from the API. Shows zone/address, exact coords,
 * accuracy, distance-from-centre, how it was verified, and a lazy Mappls map. Honest
 * "no location" state when nothing was captured. */

function pathChip(path: string | null, t: (k: string) => string) {
  if (path === "beacon") return <Chip tone="green">{t("path_beacon")}</Chip>;
  if (path === "field") return <Chip tone="blue">{t("path_field")}</Chip>;
  if (path === "gps") return <Chip tone="blue">{t("path_gps")}</Chip>;
  if (path === "location") return <Chip tone="blue">{t("path_gps")}</Chip>;
  return null;
}

export default function LocationCard({ rec }: { rec: any }) {
  const { t } = useI18n();
  const [showMap, setShowMap] = useState(false);

  const lat = rec.gps_lat ?? rec.lat ?? null;
  const lng = rec.gps_lng ?? rec.lng ?? null;
  const zone = rec.ble_zone || rec.zone || null;
  const addr = rec.geo_address || rec.address || null;
  const acc = rec.gps_accuracy ?? null;
  const dist = rec.geo_distance_m ?? null;
  const path = rec.verification_path ?? null;
  const hasCoords = lat != null && lng != null;

  if (!zone && !hasCoords) {
    return (
      <div className="loc-card muted" data-testid="loc-card">
        📍 {t("noLocation")}
        {rec.flagged_reason ? ` — ${rec.flagged_reason}` : ""}
      </div>
    );
  }

  return (
    <div className="loc-card" data-testid="loc-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        {zone && <Chip tone="green">{t("zone")}: {zone}</Chip>}
        {pathChip(path, t)}
        {acc != null && <Chip tone={acc <= 100 ? "green" : "amber"}>{t("accuracy")} ±{Math.round(acc)} m</Chip>}
        {dist != null && <Chip tone="blue">{Math.round(dist)} m {t("fromCenter")}</Chip>}
      </div>
      {addr && <div style={{ marginTop: 6, fontSize: 13 }}>{addr}</div>}
      {hasCoords && (
        <div style={{ marginTop: 4, fontFamily: "monospace", fontSize: 12, color: "var(--muted)" }}>
          {Number(lat).toFixed(5)}, {Number(lng).toFixed(5)}
        </div>
      )}
      {hasCoords && (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button className="btn sm" data-testid="toggle-map" onClick={() => setShowMap((s) => !s)}>
            {showMap ? t("hideMap") : t("showMap")}
          </button>
          <a className="btn sm" href={`https://maps.mappls.com/@${lat},${lng},17z`} target="_blank" rel="noreferrer">
            {t("openInMaps")}
          </a>
        </div>
      )}
      {showMap && hasCoords && (
        <div style={{ marginTop: 8 }}>
          <MapplsMap lat={Number(lat)} lng={Number(lng)} accuracy={acc} />
        </div>
      )}
    </div>
  );
}
