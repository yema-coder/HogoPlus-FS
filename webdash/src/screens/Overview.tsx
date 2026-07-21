import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { KPI } from "../components";
import { localName, useI18n } from "../i18n";
import { useCachedApi } from "../swr";

const HEALTH_COLOR: Record<string, string> = { green: "#22C55E", amber: "#F59E0B", red: "#E85A6F" };

/** Prompt 18: aggregate tiles moved OFF the landing view to this second tab.
 * Cache-first render (localStorage) + background refresh every 60s. */
export default function Overview() {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const { data, loading, error, refresh } = useCachedApi<any>("overview", "/dashboard/overview");
  const [pulse, setPulse] = React.useState("");

  useEffect(() => {
    api("/dashboard/pulse").then((r: any) => setPulse(r.pulse || "")).catch(() => undefined);
    const id = setInterval(refresh, 60000);
    return () => clearInterval(id);
  }, [refresh]);

  if (error && !data) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (loading && !data) {
    return (
      <div>
        <div className="topbar"><h1>{t("nav_overview")}</h1></div>
        <div className="kpis">{[1, 2, 3, 4].map((n) => <div key={n} className="skel" style={{ height: 84, borderRadius: 14 }} />)}</div>
        <div className="card"><div className="skel" style={{ height: 220 }} /></div>
      </div>
    );
  }
  const { kpis, departments } = data;

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="overview-title">{t("nav_overview")} — {data.date}</h1>
        <button className="btn ghost" onClick={refresh}>↻ {t("refresh")}</button>
      </div>
      {pulse ? (
        <div className="pulse-line" data-testid="factory-pulse">💡 {pulse}</div>
      ) : null}

      <div className="kpis" data-testid="overview-kpis">
        <KPI label={t("attendancePct")} value={`${kpis.attendance_pct}%`} />
        <KPI label={`${t("present")} / ${t("total")}`} value={`${kpis.present}/${kpis.total}`} />
        <KPI label={t("late")} value={kpis.late} />
        <KPI label={t("flagged")} value={kpis.flagged} red={kpis.flagged > 0} onClick={() => nav("/attendance")} />
        <KPI label={t("openIncidents")} value={kpis.open_incidents} red={kpis.critical_incidents > 0} onClick={() => nav("/")} />
        <KPI label={t("pendingApprovals")} value={kpis.pending_approvals} onClick={() => nav("/approvals")} />
        <KPI label={t("submissionsToday")} value={kpis.submissions_today} />
      </div>

      <div className="card">
        <h2>{t("deptHealth")}</h2>
        <div className="tiles" data-testid="dept-tiles">
          {departments.map((d: any) => (
            <div key={d.code} className={`tile ${d.health}`} data-testid={`dept-tile-${d.code}`} onClick={() => nav(`/dept/${d.code}`)}>
              <h3>{localName(d, lang)}</h3>
              <div className="row"><span>{t("attendancePct")}</span><b>{d.present}/{d.total} ({d.attendance_pct}%)</b></div>
              <div className="row"><span>{t("openIncidents")}</span><b>{d.open_incidents}{d.critical_incidents ? ` (⚠ ${d.critical_incidents})` : ""}</b></div>
              <div className="row"><span>{t("pendingApprovals")}</span><b>{d.pending_approvals}</b></div>
              <div className="row"><span>{t("submissionsToday")}</span><b>{d.submissions_today}</b></div>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>{t("attendanceByDept")}</h2>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={departments}>
            <XAxis dataKey="code" tick={{ fontSize: 11 }} interval={0} angle={-30} textAnchor="end" height={70} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="attendance_pct" radius={[6, 6, 0, 0]}>
              {departments.map((d: any) => (
                <Cell key={d.code} fill={HEALTH_COLOR[d.health] || "#0B4F6C"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
