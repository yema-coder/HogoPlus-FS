import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Chip, Loading } from "../components";
import { useI18n } from "../i18n";
import { PresenceTabs, fmtClock, fmtMin, todayIST, zoneName } from "../presence/shared";

/** v1.0.26 Phase 2 — daily time-in-zone per worker. Honesty rule: each ping
 * covers at most 10 min, so coverage % exposes tracking gaps instead of hiding
 * them. Untracked workers appear dimmed — never silently missing. */

interface SummaryZone { zone_key: string; zone_en: string; zone_hi: string | null; zone_mr: string | null; minutes: number }
interface SummaryWorker {
  id: string; emp_id: string; full_name: string; department_code: string | null;
  tracked: boolean; punch_in_at: string; punch_out_at: string | null;
  shift_min: number | null; tracked_min: number; coverage_pct: number | null;
  zones: SummaryZone[]; gps_inside_min: number; outside_min: number;
}
interface SummaryResp {
  enabled: boolean; generated_at: string; date: string; scope?: string;
  counts?: { workers: number; tracked: number; avg_coverage_pct: number };
  workers?: SummaryWorker[];
}

function CovBar({ pct }: { pct: number | null }) {
  if (pct === null) return <span style={{ color: "var(--muted)" }}>—</span>;
  const cls = pct < 40 ? "low" : pct < 75 ? "mid" : "";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span className={`cov-bar ${cls}`}><i style={{ width: `${pct}%` }} /></span>
      <b style={{ fontSize: 13 }}>{pct}%</b>
    </span>
  );
}

export default function PresenceSummary() {
  const { t, lang } = useI18n();
  const [date, setDate] = useState(todayIST());
  const [data, setData] = useState<SummaryResp | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [deptFilter, setDeptFilter] = useState("");

  const load = async (d = date) => {
    try {
      setData(await api(`/presence/shift-summary?date=${d}`));
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
  };
  useEffect(() => { load(date); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [date]);

  const workers = data?.workers ?? [];
  const depts = useMemo(
    () => Array.from(new Set(workers.map((w) => w.department_code).filter(Boolean) as string[])).sort(),
    [workers]
  );
  const shown = useMemo(() => {
    let ws = workers;
    if (deptFilter) ws = ws.filter((w) => w.department_code === deptFilter);
    const needle = q.trim().toLowerCase();
    if (needle) ws = ws.filter((w) => `${w.full_name} ${w.emp_id}`.toLowerCase().includes(needle));
    return ws;
  }, [workers, deptFilter, q]);

  if (error && !data) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!data) return <Loading />;

  return (
    <>
      <div className="topbar">
        <h1 data-testid="summary-title">🕐 {t("prs2_summary_title")}</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <input type="date" value={date} max={todayIST()} data-testid="summary-date"
                 onChange={(e) => e.target.value && setDate(e.target.value)} />
          <button className="btn ghost" style={{ padding: "6px 12px" }} onClick={() => load()}>↻ {t("refresh")}</button>
        </div>
      </div>
      <PresenceTabs active="summary" />

      {!data.enabled ? (
        <div className="card" style={{ textAlign: "center", padding: 40 }}>
          <h2>{t("prs_disabled_title")}</h2>
        </div>
      ) : (
        <>
          <div className="prs-strip" data-testid="summary-kpis">
            <div className="kpi"><div className="v">{data.counts?.workers ?? 0}</div><div className="l">{t("prs_worker_list")}</div></div>
            <div className="kpi"><div className="v">{data.counts?.tracked ?? 0}</div><div className="l">{t("prs2_tracked_workers")}</div></div>
            <div className="kpi big"><div className="v">{data.counts?.avg_coverage_pct ?? 0}%</div><div className="l">{t("prs2_avg_coverage")}</div></div>
          </div>

          <div className="card" data-testid="summary-table">
            <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
              <input placeholder={t("prs_search")} value={q} onChange={(e) => setQ(e.target.value)}
                     style={{ flex: 2, minWidth: 150 }} data-testid="summary-search" />
              <select value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)} data-testid="summary-dept">
                <option value="">{t("prs_all_depts")}</option>
                {depts.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead><tr>
                  <th>{t("prs2_worker")}</th><th>{t("prs2_punch")}</th><th>{t("prs2_shift_time")}</th>
                  <th>{t("prs2_tracked_time")}</th><th>{t("prs2_coverage")}</th>
                  <th>{t("prs2_zone_hours")}</th><th>{t("prs2_outside_min")}</th>
                </tr></thead>
                <tbody>
                  {shown.map((w) => (
                    <tr key={w.id} style={{ opacity: w.tracked ? 1 : 0.55 }} data-testid={`summary-row-${w.emp_id}`}>
                      <td>
                        <Link to={`/presence/worker/${w.id}?date=${data.date}`} style={{ color: "inherit" }}>
                          <b>{w.full_name}</b>
                        </Link>{" "}
                        <span style={{ color: "var(--muted)", fontSize: 12 }}>{w.emp_id} · {w.department_code || "—"}</span>
                        {!w.tracked && <> <Chip>{t("prs2_not_tracked_row")}</Chip></>}
                      </td>
                      <td style={{ whiteSpace: "nowrap", fontSize: 13 }}>
                        {fmtClock(w.punch_in_at)} → {w.punch_out_at ? fmtClock(w.punch_out_at) : "…"}
                      </td>
                      <td>{fmtMin(w.shift_min)}</td>
                      <td>{fmtMin(w.tracked_min)}</td>
                      <td>{w.tracked ? <CovBar pct={w.coverage_pct} /> : "—"}</td>
                      <td>
                        {w.zones.slice(0, 3).map((z) => (
                          <span key={z.zone_key} className="zone-chip">
                            {zoneName({ name_en: z.zone_en, name_hi: z.zone_hi, name_mr: z.zone_mr }, lang)} · {fmtMin(z.minutes)}
                          </span>
                        ))}
                        {w.zones.length > 3 && <span className="zone-chip">+{w.zones.length - 3}</span>}
                        {w.gps_inside_min > 0 && (
                          <span className="zone-chip">{t("prs2_inside_gps")} · {fmtMin(w.gps_inside_min)}</span>
                        )}
                        {w.zones.length === 0 && w.gps_inside_min === 0 && (
                          <span style={{ color: "var(--muted)", fontSize: 13 }}>—</span>
                        )}
                      </td>
                      <td>
                        {w.outside_min > 0
                          ? <Chip tone="red">{fmtMin(w.outside_min)}</Chip>
                          : <span style={{ color: "var(--muted)" }}>—</span>}
                      </td>
                    </tr>
                  ))}
                  {shown.length === 0 && (
                    <tr><td colSpan={7} style={{ textAlign: "center", color: "var(--muted)" }}>{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}
