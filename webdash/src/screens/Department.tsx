import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Chip, Empty, fmtTime, Loading, VerifChip } from "../components";
import { localName, useI18n } from "../i18n";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

export default function Department() {
  const { code } = useParams();
  const { t, lang } = useI18n();
  const [date, setDate] = useState(today());
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setData(null);
    setErr("");
    api(`/dashboard/department/${code}?date=${date}`).then(setData).catch((e) => setErr(e.message));
  }, [code, date]);

  if (err) return <div className="card" style={{ color: "var(--danger)" }}>{err} — <Link to="/">{t("back")}</Link></div>;
  if (!data) return <Loading />;

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="dept-title"><Link to="/">←</Link> {localName(data, lang)}</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ color: "var(--muted)", fontSize: 14 }}>
            {t("manager")}: <b style={{ color: "var(--text)" }}>{data.manager_name || t("noManager")}</b> · {data.total_employees} {t("employees")}
          </span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="dept-date" />
        </div>
      </div>

      <div className="card">
        <h2>{t("trends14")}</h2>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data.trends}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E7E4DC" />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
            <YAxis yAxisId="l" domain={[0, 100]} tick={{ fontSize: 11 }} />
            <YAxis yAxisId="r" orientation="right" allowDecimals={false} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend />
            <Line yAxisId="l" type="monotone" dataKey="attendance_pct" name={`${t("attendancePct")} %`} stroke="#0B4F6C" strokeWidth={2} dot={false} />
            <Line yAxisId="r" type="monotone" dataKey="submissions" name={t("submissions")} stroke="#3A5DAE" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>{t("attendanceRegister")} — {data.date} ({data.attendance.length})</h2>
        {data.attendance.length === 0 ? <Empty /> : (
          <table data-testid="dept-attendance-table">
            <thead>
              <tr><th>{t("empId")}</th><th>{t("name")}</th><th>{t("punchIn")}</th><th>{t("punchOut")}</th><th>{t("verification")}</th><th>{t("late")}</th></tr>
            </thead>
            <tbody>
              {data.attendance.map((a: any) => (
                <tr key={a.id} className={a.verification_level === "flagged" ? "red" : ""}>
                  <td>{a.emp_id}</td>
                  <td>{a.name}</td>
                  <td>{fmtTime(a.punch_in_at)}</td>
                  <td>{fmtTime(a.punch_out_at)}</td>
                  <td><VerifChip level={a.verification_level} />{a.flagged_reason ? <span style={{ fontSize: 12, color: "var(--muted)" }}> {a.flagged_reason}</span> : null}</td>
                  <td>{a.is_late ? <Chip tone="amber">{t("late")}</Chip> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid">
        <div className="card">
          <h2>{t("submissions")} ({data.submissions.length})</h2>
          {data.submissions.length === 0 ? <Empty /> : data.submissions.map((s: any) => (
            <div key={s.id} className="feed-item" style={{ cursor: "default" }}>
              {s.photos?.[0] ? <img src={s.photos[0]} alt="" /> : null}
              <div style={{ flex: 1 }}>
                <div className="t">{s.submitted_by_name}</div>
                <div className="m">{fmtTime(s.created_at)} · {Object.entries(s.data || {}).slice(0, 3).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>
              </div>
              <Chip tone={s.status === "approved" ? "green" : s.status === "rejected" ? "red" : "blue"}>{s.status}</Chip>
            </div>
          ))}
        </div>
        <div className="card">
          <h2>{t("openIncidents")} ({data.incidents.length})</h2>
          {data.incidents.length === 0 ? <Empty /> : data.incidents.map((i: any) => (
            <div key={i.id} className="feed-item" style={{ cursor: "default" }}>
              <div style={{ flex: 1 }}>
                <div className="t">{i.category}</div>
                <div className="m">{new Date(i.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} · {i.status}</div>
              </div>
              <Chip tone={i.severity === "critical" ? "red" : i.severity === "high" ? "amber" : undefined}>{i.severity}</Chip>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
