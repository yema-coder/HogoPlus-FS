import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Chip, Empty, fmtTime, Loading, VerifChip } from "../components";
import { localName, useI18n } from "../i18n";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

const REASON_KEY: Record<string, string> = {
  no_text_found: "rNoText",
  no_valid_plate: "rNoValidPlate",
  detection_failed: "rDetectionFailed",
};

function IncidentModal({ inc, onClose }: { inc: any; onClose: () => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const detected = inc.detected_plate && (inc.plate_status === "detected" || !inc.plate_status);
  const copyPlate = () => {
    const done = () => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    };
    const fallback = () => {
      const ta = document.createElement("textarea");
      ta.value = inc.detected_plate;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        done();
      } finally {
        document.body.removeChild(ta);
      }
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(inc.detected_plate).then(done).catch(fallback);
    } else {
      fallback();
    }
  };
  const coords =
    inc.gps_lat != null && inc.gps_lng != null
      ? `${Number(inc.gps_lat).toFixed(5)}, ${Number(inc.gps_lng).toFixed(5)}`
      : null;
  const locBlock = (label: string, testid: string) => (
    <div className="loc-block" data-testid={testid}>
      <div className="loc-label">📍 {label}</div>
      {inc.address_text ? <div style={{ fontWeight: 600 }}>{inc.address_text}</div> : null}
      {coords ? <div style={{ fontSize: 13, color: "var(--muted)" }}>{coords}</div> : null}
      {!inc.address_text && !coords ? <div style={{ color: "var(--muted)" }}>—</div> : null}
    </div>
  );
  return (
    <div className="modal-overlay" onClick={onClose} data-testid="incident-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} data-testid="incident-modal-close">✕</button>
        <h2 style={{ marginTop: 0 }}>{inc.category}</h2>
        {inc.photo_url || inc.video_url ? (
          <div className="result-media">
            {inc.video_url ? <video src={inc.video_url} controls /> : <img src={inc.photo_url} alt="" />}
            <span className="badge">
              <Chip tone={inc.status === "resolved" ? "green" : inc.status === "escalated" ? "red" : "blue"}>{inc.status}</Chip>
            </span>
          </div>
        ) : null}
        {detected ? (
          <div className="plate-card" data-testid="modal-plate-card">
            <div className="loc-label">🚗 {t("detectedPlate")}</div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <span className="plate-big" data-testid="modal-plate-text">{inc.detected_plate}</span>
              <button className="btn ghost" onClick={copyPlate} data-testid="modal-plate-copy">
                {copied ? `✓ ${t("copied")}` : `⧉ ${t("copy")}`}
              </button>
            </div>
            {inc.plate_confidence != null ? (
              <div style={{ fontSize: 13, color: "var(--muted)" }}>
                {t("confidence")}: {Math.round(inc.plate_confidence)}%{inc.plate_source === "llm_vision" ? " · AI" : ""}
              </div>
            ) : null}
          </div>
        ) : inc.plate_status === "pending" ? (
          <div className="plate-card" data-testid="modal-plate-pending">
            <div className="loc-label">🚗 {t("plateChecking")}</div>
          </div>
        ) : inc.plate_status === "not_detected" ? (
          <div className="plate-card miss" data-testid="modal-plate-missing">
            <div style={{ fontWeight: 700 }}>🚫 {t("plateNotDetected")}</div>
            {inc.plate_reason ? (
              <div style={{ fontSize: 13, color: "var(--muted)" }}>{t(REASON_KEY[inc.plate_reason] || "rNoValidPlate")}</div>
            ) : null}
          </div>
        ) : null}
        {locBlock(t("objectLocation"), "modal-object-location")}
        {locBlock(t("deviceLocation"), "modal-device-location")}
        {inc.description ? <div style={{ marginTop: 10 }}>{inc.description}</div> : null}
        <div style={{ marginTop: 10, fontSize: 13, color: "var(--muted)" }}>
          🕐 {t("capturedAt")}: {new Date(inc.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}
        </div>
      </div>
    </div>
  );
}

export default function Department() {
  const { code } = useParams();
  const { t, lang } = useI18n();
  const [date, setDate] = useState(today());
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState<any | null>(null);

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
            <div key={i.id} className="feed-item" onClick={() => setSelected(i)} data-testid={`incident-item-${i.id}`}>
              {i.photo_url ? <img src={i.photo_url} alt="" /> : null}
              <div style={{ flex: 1 }}>
                <div className="t">{i.category}{i.detected_plate ? <> · <b style={{ color: "var(--primary, #1a6b3c)" }}>🚗 {i.detected_plate}</b></> : null}</div>
                <div className="m">{new Date(i.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} · {i.status}</div>
              </div>
              <Chip tone={i.severity === "critical" ? "red" : i.severity === "high" ? "amber" : undefined}>{i.severity}</Chip>
            </div>
          ))}
        </div>
      </div>
      {selected ? <IncidentModal inc={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}
