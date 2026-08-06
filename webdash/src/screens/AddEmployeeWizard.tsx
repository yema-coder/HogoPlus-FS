import React, { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import { localName, useI18n } from "../i18n";

const ROLES = ["Worker", "Staff", "Clerk", "Manager", "CGM", "MD"];
const EMP_ID_RE = /^[A-Za-z0-9]{1,20}$/;
const normPhone = (raw: string): string | null => {
  const d = raw.replace(/\D/g, "");
  const ten =
    d.length === 12 && d.startsWith("91") ? d.slice(2)
    : d.length === 11 && d.startsWith("0") ? d.slice(1)
    : d.length === 10 ? d : null;
  return ten && /^[6-9]/.test(ten) ? `+91${ten}` : null;
};

/** Step-by-step add-employee wizard (one field per step) — field teams were
 * submitting half-empty records with the all-at-once form. Server-side
 * validation is identical regardless of client. */
export default function AddEmployeeWizard({ depts, onClose, onCreated }: {
  depts: any[]; onClose: () => void; onCreated: () => void;
}) {
  const { t, lang } = useI18n();
  const [step, setStep] = useState(0); // 0 name, 1 emp_id, 2 dept+role, 3 phone, 4 review
  const [name, setName] = useState("");
  const [empId, setEmpId] = useState("");
  const [dept, setDept] = useState("");
  const [role, setRole] = useState("Worker");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/admin/emp-id-suggest").then((r) => setEmpId((v) => v || r.suggested_emp_id)).catch(() => {});
  }, []);

  const phoneNorm = useMemo(() => normPhone(phone), [phone]);
  const stepValid = [
    name.trim().length >= 2,
    EMP_ID_RE.test(empId.trim()),
    dept !== "" && role !== "",
    phoneNorm !== null,
    true,
  ][step];

  const next = async () => {
    setErr("");
    // per-step uniqueness checks, error names the current holder
    if (step === 1 || step === 3) {
      setBusy(true);
      try {
        const q = step === 1 ? `emp_id=${encodeURIComponent(empId.trim())}` : `phone=${encodeURIComponent(phoneNorm!)}`;
        const r = await api(`/admin/employees/availability?${q}`);
        const takenBy = step === 1 ? r.emp_id_taken_by : r.phone_taken_by;
        if (takenBy) {
          setErr(`${step === 1 ? t("wiz_id_taken") : t("wiz_phone_taken")}: ${takenBy}`);
          return;
        }
      } catch (e: any) {
        setErr(e.message);
        return;
      } finally {
        setBusy(false);
      }
    }
    setStep((s) => s + 1);
  };

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      await api("/admin/employees", {
        method: "POST",
        body: JSON.stringify({
          full_name: name.trim(), emp_id: empId.trim(), department_code: dept,
          role_code: role, phone: phoneNorm,
        }),
      });
      onCreated();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const titles = [t("wiz_name"), t("empId"), t("wiz_dept_role"), t("wiz_phone"), t("wiz_review")];
  const label = { fontWeight: 600 as const, fontSize: 14, margin: "12px 0 6px" };
  const inputStyle = { width: "100%" as const, boxSizing: "border-box" as const, fontSize: 18 };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" data-testid="add-emp-wizard" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ color: "var(--primary)", fontSize: 18 }}>{t("emps_add")}</h2>
          <button onClick={onClose} aria-label="close">✕</button>
        </div>
        {/* progress */}
        <div style={{ display: "flex", gap: 6, margin: "10px 0" }} data-testid="wiz-progress">
          {titles.map((_, i) => (
            <div key={i} style={{
              flex: 1, height: 6, borderRadius: 3,
              background: i <= step ? "var(--primary)" : "var(--border)",
            }} />
          ))}
        </div>
        <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 4 }}>
          {t("wiz_step")} {step + 1}/5 — <b>{titles[step]}</b>
        </div>

        {step === 0 && (
          <>
            <div style={label}>{t("wiz_name")}</div>
            <input data-testid="wiz-name" style={inputStyle} value={name} autoFocus
              onChange={(e) => setName(e.target.value)} />
          </>
        )}
        {step === 1 && (
          <>
            <div style={label}>{t("empId")} <span style={{ color: "var(--muted)", fontWeight: 400 }}>({t("wiz_id_hint")})</span></div>
            <input data-testid="wiz-empid" style={inputStyle} value={empId} autoFocus
              onChange={(e) => setEmpId(e.target.value.toUpperCase())} />
          </>
        )}
        {step === 2 && (
          <>
            <div style={label}>{t("department")}</div>
            <select data-testid="wiz-dept" style={inputStyle} value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">—</option>
              {depts.map((d) => <option key={d.code} value={d.code}>{localName(d, lang)}</option>)}
            </select>
            <div style={label}>{t("emps_role")}</div>
            <select data-testid="wiz-role" style={inputStyle} value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </>
        )}
        {step === 3 && (
          <>
            <div style={label}>{t("wiz_phone")} <span style={{ color: "var(--muted)", fontWeight: 400 }}>({t("wiz_phone_hint")})</span></div>
            <input data-testid="wiz-phone" style={inputStyle} value={phone} autoFocus
              placeholder="+91XXXXXXXXXX" onChange={(e) => setPhone(e.target.value)} />
            {phone.length > 0 && phoneNorm === null && (
              <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("emps_bad_phone")}</div>
            )}
          </>
        )}
        {step === 4 && (
          <table data-testid="wiz-review">
            <tbody>
              <tr><td style={{ fontWeight: 600 }}>{t("wiz_name")}</td><td>{name.trim()}</td></tr>
              <tr><td style={{ fontWeight: 600 }}>{t("empId")}</td><td>{empId.trim()}</td></tr>
              <tr><td style={{ fontWeight: 600 }}>{t("department")}</td><td>{dept}</td></tr>
              <tr><td style={{ fontWeight: 600 }}>{t("emps_role")}</td><td>{role}</td></tr>
              <tr><td style={{ fontWeight: 600 }}>{t("wiz_phone")}</td><td>{phoneNorm}</td></tr>
            </tbody>
          </table>
        )}

        {err && <div data-testid="wiz-error" style={{ color: "var(--danger)", fontWeight: 600, marginTop: 8 }}>{err}</div>}

        <div style={{ display: "flex", gap: 10, marginTop: 18, justifyContent: "space-between" }}>
          <button
            data-testid="wiz-back"
            onClick={() => (step === 0 ? onClose() : (setErr(""), setStep((s) => s - 1)))}
            style={{ padding: "10px 18px", borderRadius: 10, border: "2px solid var(--border)", background: "var(--surface)" }}
          >
            ← {t("emps_back")}
          </button>
          {step < 4 ? (
            <button
              data-testid="wiz-next"
              disabled={!stepValid || busy}
              onClick={next}
              style={{
                padding: "10px 22px", borderRadius: 10, border: "none", fontWeight: 700,
                background: stepValid && !busy ? "var(--primary)" : "var(--border)",
                color: stepValid && !busy ? "#fff" : "var(--muted)",
              }}
            >
              {busy ? t("wiz_checking") : `${t("wiz_next")} →`}
            </button>
          ) : (
            <button
              data-testid="wiz-confirm"
              disabled={busy}
              onClick={submit}
              style={{ padding: "10px 22px", borderRadius: 10, border: "none", fontWeight: 700, background: "var(--success)", color: "#fff" }}
            >
              {busy ? "…" : `✓ ${t("emps_add")}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
