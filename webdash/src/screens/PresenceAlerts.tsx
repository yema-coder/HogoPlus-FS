import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Chip, Loading } from "../components";
import { useI18n } from "../i18n";
import { ALERT_EMOJI, PresenceTabs, fmtClock } from "../presence/shared";

/** v1.0.26 Phase 2 — live alerts panel: outside geofence / gone dark /
 * low battery / unauthorized zone. Ack + resolve, 15 s auto-refresh. */

const REFRESH_MS = 15_000;
const TYPES = ["outside_geofence", "gone_dark", "low_battery", "unauthorized_zone"];

interface AlertRow {
  id: string; employee_id: string; emp_id: string; full_name: string;
  department_code: string | null; alert_type: string; status: string;
  zone_key: string | null; zone_en: string | null; detail: Record<string, any>;
  first_seen_at: string; last_seen_at: string;
  acknowledged_at: string | null; resolved_at: string | null; auto_resolved: boolean;
}
interface AlertsResp {
  generated_at: string; open_total: number;
  open_by_type: Record<string, number>; alerts: AlertRow[];
}

export default function PresenceAlerts() {
  const { t } = useI18n();
  const [data, setData] = useState<AlertsResp | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [typeFilter, setTypeFilter] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const timer = useRef<any>(null);

  const load = async (resolved = showResolved) => {
    try {
      setData(await api(`/presence/alerts?status=${resolved ? "all" : "open"}`));
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load(showResolved);
    timer.current = setInterval(() => load(showResolved), REFRESH_MS);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showResolved]);

  const act = async (id: string, action: "ack" | "resolve") => {
    setBusy(id + action);
    try {
      await api(`/presence/alerts/${id}/${action}`, { method: "POST" });
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  };

  const detailText = (a: AlertRow): string => {
    if (a.alert_type === "outside_geofence") return `${a.detail?.minutes ?? 0} ${t("prs2_min_outside")}`;
    if (a.alert_type === "gone_dark") return `${a.detail?.minutes ?? 0} ${t("prs2_min_silent")}`;
    if (a.alert_type === "low_battery") return `🔋 ${a.detail?.battery_pct ?? "?"}%`;
    return `${a.zone_en || a.detail?.zone_en || a.zone_key || "?"}${a.detail?.zone_dept ? ` (${a.detail.zone_dept})` : ""}`;
  };

  if (error && !data) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!data) return <Loading />;

  const shown = typeFilter ? data.alerts.filter((a) => a.alert_type === typeFilter) : data.alerts;

  return (
    <>
      <div className="topbar"><h1 data-testid="alerts-title">🚨 {t("prs2_alerts_title")}</h1></div>
      <PresenceTabs active="alerts" />

      <div className="prs-strip" data-testid="alerts-kpis">
        {TYPES.map((k) => (
          <div key={k} className={`kpi ${typeFilter === k ? "sel" : ""}`} data-testid={`alert-kpi-${k}`}
               onClick={() => setTypeFilter(typeFilter === k ? "" : k)}>
            <div className={`v ${(data.open_by_type[k] ?? 0) > 0 ? "red" : ""}`}>{data.open_by_type[k] ?? 0}</div>
            <div className="l">{ALERT_EMOJI[k]} {t(`prs2_type_${k}`)}</div>
          </div>
        ))}
      </div>

      <div className="card" data-testid="alerts-table">
        <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>{t("prs2_alerts_title")} ({shown.length})</h2>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600 }}>
            <input type="checkbox" checked={showResolved} data-testid="show-resolved"
                   onChange={(e) => setShowResolved(e.target.checked)} />
            {t("prs2_show_resolved")}
          </label>
        </div>
        {shown.length === 0 ? (
          <div style={{ padding: 28, textAlign: "center", color: "var(--muted)", fontWeight: 600 }}
               data-testid="alerts-empty">✅ {t("prs2_no_alerts")}</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr>
                <th>{t("prs2_worker")}</th><th>{t("status")}</th><th></th>
                <th>{t("prs2_since")}</th><th>{t("prs_last_seen")}</th><th></th>
              </tr></thead>
              <tbody>
                {shown.map((a) => (
                  <tr key={a.id} className={a.status === "active" ? "red" : ""} data-testid={`alert-row-${a.id}`}>
                    <td>
                      <Link to={`/presence/worker/${a.employee_id}`} style={{ color: "inherit" }}>
                        <b>{a.full_name}</b>
                      </Link>{" "}
                      <span style={{ color: "var(--muted)", fontSize: 12 }}>{a.emp_id} · {a.department_code || "—"}</span>
                    </td>
                    <td>
                      <Chip tone={a.status === "resolved" ? "green" : a.status === "acknowledged" ? "amber" : "red"}>
                        {ALERT_EMOJI[a.alert_type]} {t(`prs2_type_${a.alert_type}`)}
                      </Chip>
                    </td>
                    <td style={{ fontSize: 13, fontWeight: 600 }}>{detailText(a)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtClock(a.first_seen_at)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>{fmtClock(a.last_seen_at)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {a.status === "active" && (
                        <button className="btn ghost" style={{ padding: "5px 10px", marginRight: 6 }}
                                disabled={busy === a.id + "ack"} data-testid={`ack-${a.id}`}
                                onClick={() => act(a.id, "ack")}>
                          {t("prs2_ack")}
                        </button>
                      )}
                      {a.status !== "resolved" ? (
                        <button className="btn primary" style={{ padding: "5px 10px" }}
                                disabled={busy === a.id + "resolve"} data-testid={`resolve-${a.id}`}
                                onClick={() => act(a.id, "resolve")}>
                          {t("prs2_resolve")}
                        </button>
                      ) : (
                        <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600 }}>
                          {t("prs2_resolved")}{a.auto_resolved ? ` · ${t("prs2_auto")}` : ""}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
