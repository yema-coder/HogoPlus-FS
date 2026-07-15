import React, { useEffect, useState } from "react";
import { api } from "../api";
import { canReviewAttendance, isTopMgmt, useAuth } from "../auth";
import { Chip, Empty, fmtTime, Loading, VerifChip } from "../components";
import { localName, useI18n } from "../i18n";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

export default function Attendance() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const all = isTopMgmt(user);
  const [depts, setDepts] = useState<any[]>([]);
  const [dept, setDept] = useState(user?.department_code || "");
  const [date, setDate] = useState(today());
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api("/departments").then((d) => {
      setDepts(d);
      if (all && !dept && d.length) setDept(d[0].code);
    });
  }, []);

  const load = () => {
    if (!dept) return;
    setData(null);
    setErr("");
    api(`/dashboard/department/${dept}?date=${date}`).then(setData).catch((e) => setErr(e.message));
  };
  useEffect(load, [dept, date]);

  const review = async (id: string, action: "approve" | "reject") => {
    setBusy(id);
    try {
      await api(`/attendance/${id}/${action}`, { method: "POST" });
      load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const canReview = canReviewAttendance(user);

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="attendance-title">{t("attendanceRegister")}</h1>
        <div style={{ display: "flex", gap: 10 }}>
          {all ? (
            <select data-testid="attendance-dept-select" value={dept} onChange={(e) => setDept(e.target.value)}>
              {depts.map((d) => <option key={d.code} value={d.code}>{localName(d, lang)}</option>)}
            </select>
          ) : (
            <Chip tone="blue">{dept}</Chip>
          )}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="attendance-date" />
        </div>
      </div>

      {err && <div className="card" style={{ color: "var(--danger)" }}>{err}</div>}
      {!data ? (!err && <Loading />) : (
        <div className="card">
          <h2>{dept} — {data.date} · {data.attendance.length}/{data.total_employees} {t("present")}</h2>
          {data.attendance.length === 0 ? <Empty /> : (
            <table data-testid="attendance-table">
              <thead>
                <tr>
                  <th>{t("empId")}</th><th>{t("name")}</th><th>{t("punchIn")}</th><th>{t("punchOut")}</th>
                  <th>{t("verification")}</th><th>{t("faceScore")}</th><th>{t("late")}</th>
                  {canReview && <th>{t("actions")}</th>}
                </tr>
              </thead>
              <tbody>
                {data.attendance.map((a: any) => {
                  const pendingFlag = a.verification_level === "flagged" && !a.approved_by;
                  return (
                    <tr key={a.id} className={pendingFlag ? "red" : a.is_late ? "amber" : ""}>
                      <td>{a.emp_id}</td>
                      <td>{a.name}</td>
                      <td>{fmtTime(a.punch_in_at)}</td>
                      <td>{fmtTime(a.punch_out_at)}</td>
                      <td>
                        <VerifChip level={a.verification_level} />
                        {a.flagged_reason && <div style={{ fontSize: 12, color: "var(--muted)" }}>{a.flagged_reason}</div>}
                      </td>
                      <td>{a.face_match_score != null ? `${Math.round(a.face_match_score)}%` : "—"}</td>
                      <td>{a.is_late ? <Chip tone="amber">{t("late")}</Chip> : "—"}</td>
                      {canReview && (
                        <td>
                          {pendingFlag ? (
                            <div style={{ display: "flex", gap: 6 }}>
                              <button className="btn success" data-testid={`approve-${a.emp_id}`} disabled={busy === a.id} onClick={() => review(a.id, "approve")}>{t("approve")}</button>
                              <button className="btn danger" data-testid={`reject-${a.emp_id}`} disabled={busy === a.id} onClick={() => review(a.id, "reject")}>{t("reject")}</button>
                            </div>
                          ) : a.approved_by ? <Chip tone="green">✓</Chip> : "—"}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
