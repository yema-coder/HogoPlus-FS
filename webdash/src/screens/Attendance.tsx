import React, { useEffect, useState } from "react";
import { api, apiDownload } from "../api";
import { canReviewAttendance, isTopMgmt, useAuth } from "../auth";
import { Chip, Empty, fmtTime, KPI, Loading, VerifChip } from "../components";
import { localName, useI18n } from "../i18n";
import LocationCard from "../LocationCard";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const ALL = "__ALL__";

/* ---------------- one flagged punch (rich review card) ---------------- */
function FlaggedCard({
  a, canReview, checked, onCheck, onReview,
}: {
  a: any; canReview: boolean; checked: boolean;
  onCheck: (id: string, on: boolean) => void;
  onReview: (id: string, action: "approve" | "reject", note: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const act = async (action: "approve" | "reject") => {
    setBusy(action);
    try { await onReview(a.id, action, note); } finally { setBusy(""); }
  };
  const isAuto = a.punch_out_source === "auto";
  return (
    <div className="flag-row" data-testid={`flag-card-${a.emp_id}`}>
      <div className="head">
        {canReview && (
          <input type="checkbox" checked={checked} onChange={(e) => onCheck(a.id, e.target.checked)}
            data-testid={`select-${a.emp_id}`} style={{ width: 18, height: 18 }} />
        )}
        <div className="flag-selfies">
          {a.selfie_url && <img src={a.selfie_url} alt={t("selfie")} title={t("selfie")} />}
          {a.reference_selfie_url && <img src={a.reference_selfie_url} alt={t("referencePhoto")} title={t("referencePhoto")} />}
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontWeight: 800 }}>{a.employee_name} <span style={{ color: "var(--muted)", fontWeight: 500 }}>· {a.emp_id}</span></div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}>{a.department_code || "—"} · {fmtTime(a.punch_in_at)}</div>
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
            {isAuto ? <Chip tone="amber">{t("autoPunchOut")}</Chip> : <VerifChip level={a.verification_level} />}
            {a.face_match_score != null && <Chip tone="blue">{t("faceScore")} {Math.round(a.face_match_score)}%</Chip>}
          </div>
          {a.flagged_reason && <div style={{ fontSize: 13, color: "var(--danger)", marginTop: 4 }}>{a.flagged_reason}</div>}
        </div>
      </div>
      <div style={{ marginTop: 10 }}><LocationCard rec={a} /></div>
      {canReview && (
        <div>
          <input className="note-input" placeholder={t("notePh")} value={note}
            onChange={(e) => setNote(e.target.value)} data-testid={`note-${a.emp_id}`} />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button className="btn success" data-testid={`approve-${a.emp_id}`} disabled={!!busy} onClick={() => act("approve")}>{t("approve")}</button>
            <button className="btn danger" data-testid={`reject-${a.emp_id}`} disabled={!!busy} onClick={() => act("reject")}>{t("reject")}</button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- department table (present rows, expandable) ---------------- */
function DeptRow({ a, canReview, onReview }: { a: any; canReview: boolean; onReview: (id: string, action: "approve" | "reject") => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const pendingFlag = a.verification_level === "flagged" && !a.approved_by;
  const hasLoc = a.gps_lat != null || a.ble_zone;
  return (
    <>
      <tr className={pendingFlag ? "red" : a.is_late ? "amber" : ""}>
        <td>{a.emp_id}</td>
        <td>{a.name}</td>
        <td>{fmtTime(a.punch_in_at)}</td>
        <td>{fmtTime(a.punch_out_at)}</td>
        <td><VerifChip level={a.verification_level} />{a.flagged_reason && <div style={{ fontSize: 12, color: "var(--muted)" }}>{a.flagged_reason}</div>}</td>
        <td>{a.face_match_score != null ? `${Math.round(a.face_match_score)}%` : "—"}</td>
        <td>{a.is_late ? <Chip tone="amber">{t("late")}</Chip> : "—"}</td>
        <td>
          {hasLoc ? <button className="btn sm" data-testid={`loc-${a.emp_id}`} onClick={() => setOpen((o) => !o)}>📍</button> : "—"}
          {canReview && pendingFlag && (
            <span style={{ display: "inline-flex", gap: 6, marginLeft: 6 }}>
              <button className="btn success" data-testid={`approve-${a.emp_id}`} onClick={() => onReview(a.id, "approve")}>{t("approve")}</button>
              <button className="btn danger" data-testid={`reject-${a.emp_id}`} onClick={() => onReview(a.id, "reject")}>{t("reject")}</button>
            </span>
          )}
        </td>
      </tr>
      {open && (
        <tr><td colSpan={8}><LocationCard rec={a} /></td></tr>
      )}
    </>
  );
}

export default function Attendance() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const all = isTopMgmt(user);
  const canReview = canReviewAttendance(user);

  const [tab, setTab] = useState<"review" | "report">("review");
  const [depts, setDepts] = useState<any[]>([]);
  const [dept, setDept] = useState(user?.department_code || "");
  const [date, setDate] = useState(today());
  const [data, setData] = useState<any>(null);          // dept detail (review)
  const [flaggedRows, setFlaggedRows] = useState<any[] | null>(null);
  const [report, setReport] = useState<any>(null);       // daily report
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkNote, setBulkNote] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api("/departments").then((d) => {
      setDepts(d);
      if (all && !dept) setDept(ALL);
    });
  }, []);

  const loadReview = () => {
    if (!dept) return;
    setData(null); setFlaggedRows(null); setErr(""); setSelected(new Set());
    if (dept === ALL) {
      api(`/attendance/flagged?date=${date}`).then(setFlaggedRows).catch((e) => setErr(e.message));
    } else {
      // /attendance/department/{code} returns the ROW LIST this table renders.
      // (/dashboard/department/{code} is the drill-down OBJECT — rendering that as
      // an array is what white-screened this tab on 13 Oct.)
      api(`/attendance/department/${dept}?date=${date}`).then(setData).catch((e) => setErr(e.message));
    }
  };
  const loadReport = () => {
    setReport(null); setErr("");
    api(`/dashboard/daily-attendance?date=${date}`).then(setReport).catch((e) => setErr(e.message));
  };
  useEffect(() => { tab === "review" ? loadReview() : loadReport(); }, [dept, date, tab]);

  const review = async (id: string, action: "approve" | "reject", note = "") => {
    try {
      await api(`/attendance/${id}/${action}`, { method: "POST", body: JSON.stringify({ note: note || null }) });
      tab === "review" ? loadReview() : loadReport();
    } catch (e: any) { setErr(e.message); }
  };
  const toggle = (id: string, on: boolean) => {
    setSelected((s) => { const n = new Set(s); on ? n.add(id) : n.delete(id); return n; });
  };
  const bulkApprove = async () => {
    if (selected.size === 0) return;
    setBusy("bulk");
    try {
      await api("/attendance/approve-bulk", { method: "POST", body: JSON.stringify({ ids: [...selected], note: bulkNote || null }) });
      setBulkNote(""); loadReview();
    } catch (e: any) { setErr(e.message); } finally { setBusy(""); }
  };
  const download = (fmt: "pdf" | "xlsx") =>
    apiDownload(`/dashboard/daily-attendance/export?date=${date}&format=${fmt}`, `attendance_${date}.${fmt}`).catch((e) => setErr(e.message));

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="attendance-title">{t("attendanceRegister")}</h1>
        <div style={{ display: "flex", gap: 10, marginRight: 150 }}>
          {all && tab === "review" ? (
            <select data-testid="attendance-dept-select" value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value={ALL}>{t("allDepartments")}</option>
              {depts.map((d) => <option key={d.code} value={d.code}>{localName(d, lang)}</option>)}
            </select>
          ) : tab === "review" ? <Chip tone="blue">{dept}</Chip> : null}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="attendance-date" />
        </div>
      </div>

      <div className="tabs">
        <button className={tab === "review" ? "on" : ""} onClick={() => setTab("review")} data-testid="tab-review">{t("tab_review")}</button>
        <button className={tab === "report" ? "on" : ""} onClick={() => setTab("report")} data-testid="tab-report">{t("tab_report")}</button>
      </div>

      {err && <div className="card" style={{ color: "var(--danger)" }}>{err}</div>}

      {/* ---------------- REVIEW ---------------- */}
      {tab === "review" && (dept === ALL ? (
        !flaggedRows ? (!err && <Loading />) : (
          <div className="card" data-testid="attendance-flagged-list">
            <h2>{t("allDepartments")} — {date} · {flaggedRows.length} {t("pendingFlagged")}</h2>
            {canReview && selected.size > 0 && (
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
                <input className="note-input" style={{ marginTop: 0 }} placeholder={t("notePh")} value={bulkNote} onChange={(e) => setBulkNote(e.target.value)} data-testid="bulk-note" />
                <button className="btn success" disabled={busy === "bulk"} onClick={bulkApprove} data-testid="bulk-approve">{t("bulkApprove")} ({selected.size})</button>
              </div>
            )}
            {flaggedRows.length === 0 ? <Empty /> : flaggedRows.map((a) => (
              <FlaggedCard key={a.id} a={a} canReview={canReview} checked={selected.has(a.id)} onCheck={toggle} onReview={review} />
            ))}
          </div>
        )
      ) : !data ? (!err && <Loading />) : (
        (() => {
          // never trust the payload shape: an object, an error body or a partial
          // response must degrade to "no rows", not unmount the whole screen.
          const rows: any[] = Array.isArray(data) ? data : (Array.isArray(data?.attendance) ? data.attendance : []);
          return (
        <div className="card">
          <h2>{dept} — {date} · {rows.length} {t("present")}</h2>
          {rows.length === 0 ? <Empty /> : (
            <table data-testid="attendance-table">
              <thead>
                <tr>
                  <th>{t("empId")}</th><th>{t("name")}</th><th>{t("punchIn")}</th><th>{t("punchOut")}</th>
                  <th>{t("verification")}</th><th>{t("faceScore")}</th><th>{t("late")}</th><th>{t("actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a: any) => <DeptRow key={a.id} a={a} canReview={canReview} onReview={review} />)}
              </tbody>
            </table>
          )}
        </div>
          );
        })()
      ))}

      {/* ---------------- DAILY REPORT ---------------- */}
      {tab === "report" && (!report ? (!err && <Loading />) : (() => {
        // same rule as the review tab: a missing/partial payload must render an
        // empty report, never throw and blank the page.
        const totals = report?.totals ?? {};
        const departments: any[] = Array.isArray(report?.departments) ? report.departments : [];
        return (
        <div data-testid="attendance-report">
          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
              <h2 style={{ margin: 0 }}>{t("summary")} — {report.date}</h2>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn primary" onClick={() => download("pdf")} data-testid="download-pdf">{t("downloadPdf")}</button>
                <button className="btn ghost" onClick={() => download("xlsx")} data-testid="download-xlsx">{t("downloadExcel")}</button>
              </div>
            </div>
            <div className="kpi-row" style={{ marginTop: 14 }}>
              <KPI label={t("present")} value={totals.present ?? 0} />
              <KPI label={t("absent")} value={totals.absent ?? 0} red={(totals.absent ?? 0) > 0} />
              <KPI label={t("flaggedCount")} value={totals.flagged ?? 0} red={(totals.flagged ?? 0) > 0} />
              <KPI label={t("autoPunchOut")} value={totals.auto_punch_out ?? 0} />
              <KPI label={t("late")} value={totals.late ?? 0} />
            </div>
          </div>

          {departments.map((d: any) => (
            <div className="card" key={d.code} data-testid={`report-dept-${d.code}`}>
              <h2>
                {lang === "en" ? d.name_en : d.name_mr}
                {d.is_field && <Chip tone="green">&nbsp;{t("fieldDept")}</Chip>}
                <span style={{ fontWeight: 500, color: "var(--muted)", fontSize: 14 }}> · {d.present ?? 0}/{(d.present ?? 0) + (d.absent ?? 0)} {t("present")}</span>
              </h2>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                {d.flagged > 0 && <Chip tone="red">{t("flaggedCount")}: {d.flagged}</Chip>}
                {d.auto_punch_out > 0 && <Chip tone="amber">{t("autoPunchOut")}: {d.auto_punch_out}</Chip>}
                {d.late > 0 && <Chip tone="amber">{t("late")}: {d.late}</Chip>}
              </div>

              {(d.present_rows?.length ?? 0) > 0 && (
                <table>
                  <thead>
                    <tr><th>{t("empId")}</th><th>{t("name")}</th><th>{t("punchIn")}</th><th>{t("punchOut")}</th><th>{t("hours")}</th><th>{t("verification")}</th><th>{t("location")}</th></tr>
                  </thead>
                  <tbody>
                    {(d.present_rows ?? []).map((r: any) => (
                      <tr key={r.attendance_id} className={r.verification_level === "flagged" ? "red" : r.is_late ? "amber" : ""}>
                        <td>{r.emp_id}</td>
                        <td>{r.name}</td>
                        <td>{r.punch_in}</td>
                        <td>{r.punch_out}{r.auto_punch_out && <Chip tone="amber">A</Chip>}</td>
                        <td>{r.hours}</td>
                        <td><VerifChip level={r.verification_level} />{r.flagged_reason && <div style={{ fontSize: 12, color: "var(--muted)" }}>{lang === "en" ? r.reason_en : r.reason_mr}</div>}</td>
                        <td style={{ fontSize: 12 }}>{lang === "en" ? r.path_en : r.path_mr}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {(d.absent_names?.length ?? 0) > 0 && (
                <div>
                  <div style={{ fontWeight: 700, marginTop: 10, color: "var(--danger)" }}>{t("absent")} ({d.absent})</div>
                  <div className="name-list">
                    {(d.absent_names ?? []).map((p: any) => <span className="name-pill absent" key={p.emp_id}>{p.name} · {p.emp_id}</span>)}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        );
      })())}
    </div>
  );
}
