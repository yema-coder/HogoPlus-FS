import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { AgeChip, Chip, KPI, Loading } from "../components";
import { localName, useI18n } from "../i18n";

const HEALTH_COLOR: Record<string, string> = { green: "#22C55E", amber: "#F59E0B", red: "#E85A6F" };

export default function Overview() {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("");

  const load = () => api("/dashboard/overview").then(setData).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);

  if (err) return <div className="card" style={{ color: "var(--danger)" }}>{err}</div>;
  if (!data) return <Loading />;
  const { kpis, departments, incidents } = data;
  const q = filter.trim().toLowerCase().replace(/\s/g, "");
  const shownIncidents = q
    ? incidents.filter((i: any) =>
        [i.detected_plate, i.category, i.department_code, i.reporter_name, i.address_text]
          .filter(Boolean)
          .some((v: string) => v.toLowerCase().replace(/\s/g, "").includes(q)),
      )
    : incidents;

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="overview-title">{t("nav_overview")} — {data.date}</h1>
        <button className="btn ghost" onClick={load}>↻ {t("refresh")}</button>
      </div>

      <div className="kpis" data-testid="overview-kpis">
        <KPI label={t("attendancePct")} value={`${kpis.attendance_pct}%`} />
        <KPI label={`${t("present")} / ${t("total")}`} value={`${kpis.present}/${kpis.total}`} />
        <KPI label={t("late")} value={kpis.late} />
        <KPI label={t("flagged")} value={kpis.flagged} red={kpis.flagged > 0} onClick={() => nav("/attendance")} />
        <KPI label={t("openIncidents")} value={kpis.open_incidents} red={kpis.critical_incidents > 0} />
        <KPI label={t("pendingApprovals")} value={kpis.pending_approvals} onClick={() => nav("/approvals")} />
        <KPI label={t("submissionsToday")} value={kpis.submissions_today} />
      </div>

      <div className="grid">
        <div>
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

        <div className="card">
          <h2>{t("liveIncidents")}</h2>
          <input
            data-testid="incident-search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("searchIncidents")}
            style={{ marginBottom: 10 }}
          />
          {shownIncidents.length === 0 && <div style={{ color: "var(--muted)" }}>{t("noData")}</div>}
          {shownIncidents.map((i: any) => (
            <div key={i.id} className="feed-item" onClick={() => nav(`/dept/${i.department_code}`)}>
              {i.video_url ? (
                <video src={i.video_url} style={{ width: 52, height: 52, borderRadius: 8, objectFit: "cover" }} muted preload="metadata" />
              ) : i.photo_url ? <img src={i.photo_url} alt="" /> : <div style={{ width: 52, height: 52, borderRadius: 8, background: "var(--bg)", display: "flex", alignItems: "center", justifyContent: "center" }}>⚠️</div>}
              <div style={{ flex: 1 }}>
                <div className="t">{i.category} · {i.department_code}{i.video_url ? " · 🎬" : ""}</div>
                <div className="m">{i.reporter_name} · {i.status}{i.detected_plate ? <> · <b style={{ color: "var(--primary, #1a6b3c)" }}>🚗 {i.detected_plate}</b></> : null}</div>
                {i.address_text ? <div className="m">📍 {i.address_text}</div> : null}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
                <Chip tone={i.severity === "critical" ? "red" : i.severity === "high" ? "amber" : undefined}>{i.severity}</Chip>
                <AgeChip hours={i.age_hours} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
