import React, { useEffect, useMemo, useState } from "react";

import { api } from "../api";
import { Chip, Empty, Loading } from "../components";
import { localName, useI18n } from "../i18n";

const ROLES = ["Worker", "Staff", "Clerk", "Manager", "CGM", "MD"];
const EMP_ID_RE = /^[A-Za-z0-9]{1,20}$/;

/** +91XXXXXXXXXX — the exact format the login flow matches on (employee-0061 lesson). */
const normPhone = (raw: string): string | null => {
  const d = raw.replace(/\D/g, "");
  const ten =
    d.length === 12 && d.startsWith("91") ? d.slice(2)
    : d.length === 11 && d.startsWith("0") ? d.slice(1)
    : d.length === 10 ? d : null;
  return ten && /^[6-9]/.test(ten) ? `+91${ten}` : null;
};

type Emp = {
  id: string; emp_id: string; full_name: string; phone: string | null;
  department_code: string | null; role_code: string; is_active: boolean;
  onboarding_status: string;
};
type Draft = { full_name: string; phone: string; emp_id: string; department_code: string; role_code: string };
type Change = { field: string; old: string; next: string; payloadKey: string; payloadValue: string };

const draftOf = (e: Emp): Draft => ({
  full_name: e.full_name, phone: e.phone ?? "", emp_id: e.emp_id,
  department_code: e.department_code ?? "", role_code: e.role_code,
});

function StatusChip({ e }: { e: Emp }) {
  const { t } = useI18n();
  if (!e.is_active) return <Chip tone="red">{t("emps_inactive")}</Chip>;
  if (e.onboarding_status !== "approved") return <Chip tone="amber">{t("emps_pending")}</Chip>;
  return <Chip tone="green">{t("emps_active")}</Chip>;
}

function Editor({ emp, depts, onClose, onSaved }: {
  emp: Emp; depts: any[]; onClose: () => void; onSaved: () => void;
}) {
  const { t, lang } = useI18n();
  const [draft, setDraft] = useState<Draft>(draftOf(emp));
  const [step, setStep] = useState<"edit" | "confirm" | "history">("edit");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [history, setHistory] = useState<any[] | null>(null);

  const set = (k: keyof Draft, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  // ---- validation + diff ----
  const phoneNorm = draft.phone.trim() === "" ? (emp.phone ? null : "") : normPhone(draft.phone);
  const phoneBad = phoneNorm === null;
  const empIdBad = !EMP_ID_RE.test(draft.emp_id.trim());
  const nameBad = draft.full_name.trim().length === 0;
  const invalid = phoneBad || empIdBad || nameBad;

  const changes: Change[] = useMemo(() => {
    const out: Change[] = [];
    const name = draft.full_name.trim();
    if (name && name !== emp.full_name)
      out.push({ field: t("name"), old: emp.full_name, next: name, payloadKey: "full_name", payloadValue: name });
    if (!phoneBad && phoneNorm && phoneNorm !== (emp.phone ?? ""))
      out.push({ field: t("emps_phone"), old: emp.phone ?? "—", next: phoneNorm, payloadKey: "phone", payloadValue: phoneNorm });
    const eid = draft.emp_id.trim();
    if (!empIdBad && eid !== emp.emp_id)
      out.push({ field: t("empId"), old: emp.emp_id, next: eid, payloadKey: "emp_id", payloadValue: eid });
    if (draft.department_code && draft.department_code !== (emp.department_code ?? ""))
      out.push({ field: t("department"), old: emp.department_code ?? "—", next: draft.department_code, payloadKey: "department_code", payloadValue: draft.department_code });
    if (draft.role_code !== emp.role_code)
      out.push({ field: t("emps_role"), old: emp.role_code, next: draft.role_code, payloadKey: "role_code", payloadValue: draft.role_code });
    return out;
  }, [draft, emp, phoneBad, empIdBad, phoneNorm, t]);

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      const body: Record<string, string> = {};
      for (const c of changes) body[c.payloadKey] = c.payloadValue;
      await api(`/admin/employees/${emp.id}`, { method: "PATCH", body: JSON.stringify(body) });
      onSaved();
    } catch (e: any) {
      setErr(e.message);
      setStep("edit");
    } finally {
      setBusy(false);
    }
  };

  const loadHistory = () => {
    setStep("history");
    if (history === null)
      api(`/admin/employees/${emp.id}/history`).then(setHistory).catch((e) => setErr(e.message));
  };

  const label = { fontWeight: 600 as const, fontSize: 13, marginTop: 10, marginBottom: 4 };
  const inputStyle = { width: "100%" as const, boxSizing: "border-box" as const };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" data-testid="emp-editor" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <h2 style={{ color: "var(--primary)", fontSize: 18 }}>
            {step === "history" ? t("emps_history") : step === "confirm" ? t("emps_review") : t("emps_edit")}
            {" · "}{emp.emp_id}
          </h2>
          <div style={{ display: "flex", gap: 8 }}>
            {step === "edit" && (
              <button data-testid="emp-history-btn" onClick={loadHistory}>🕐 {t("emps_history")}</button>
            )}
            <button onClick={onClose} aria-label="close">✕</button>
          </div>
        </div>

        {err && <div style={{ color: "var(--danger)", fontWeight: 600, margin: "8px 0" }} data-testid="emp-editor-error">{err}</div>}

        {step === "edit" && (
          <>
            <div style={label}>{t("name")}</div>
            <input data-testid="emp-field-name" style={inputStyle} value={draft.full_name}
              onChange={(e) => set("full_name", e.target.value)} />
            {nameBad && <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("emps_bad_name")}</div>}

            <div style={label}>{t("emps_phone")}</div>
            <input data-testid="emp-field-phone" style={inputStyle} value={draft.phone}
              placeholder="+91XXXXXXXXXX" onChange={(e) => set("phone", e.target.value)} />
            {phoneBad && <div style={{ color: "var(--danger)", fontSize: 13 }} data-testid="emp-bad-phone">{t("emps_bad_phone")}</div>}

            <div style={label}>{t("empId")}</div>
            <input data-testid="emp-field-empid" style={inputStyle} value={draft.emp_id}
              onChange={(e) => set("emp_id", e.target.value)} />
            {empIdBad && <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("emps_bad_empid")}</div>}

            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={label}>{t("department")}</div>
                <select data-testid="emp-dept-select" style={inputStyle} value={draft.department_code}
                  onChange={(e) => set("department_code", e.target.value)}>
                  {depts.map((d) => <option key={d.code} value={d.code}>{localName(d, lang)}</option>)}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <div style={label}>{t("emps_role")}</div>
                <select data-testid="emp-role-select" style={inputStyle} value={draft.role_code}
                  onChange={(e) => set("role_code", e.target.value)}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 18, justifyContent: "flex-end" }}>
              <button onClick={onClose} style={{ padding: "10px 18px", borderRadius: 10, border: "2px solid var(--border)", background: "var(--surface)" }}>
                {t("emps_cancel")}
              </button>
              <button
                data-testid="emp-review-btn"
                disabled={invalid || changes.length === 0}
                onClick={() => setStep("confirm")}
                style={{
                  padding: "10px 18px", borderRadius: 10, border: "none", fontWeight: 700,
                  background: invalid || changes.length === 0 ? "var(--border)" : "var(--primary)",
                  color: invalid || changes.length === 0 ? "var(--muted)" : "#fff",
                }}
              >
                {changes.length === 0 ? t("emps_no_changes") : `${t("emps_review")} (${changes.length})`}
              </button>
            </div>
          </>
        )}

        {step === "confirm" && (
          <>
            <p style={{ color: "var(--muted)", fontSize: 14, marginBottom: 10 }}>{t("emps_confirm_note")}</p>
            <table data-testid="emp-confirm-table">
              <thead>
                <tr><th>{t("emps_field")}</th><th>{t("emps_old")}</th><th></th><th>{t("emps_new")}</th></tr>
              </thead>
              <tbody>
                {changes.map((c) => (
                  <tr key={c.payloadKey}>
                    <td style={{ fontWeight: 600 }}>{c.field}</td>
                    <td style={{ color: "var(--muted)" }}>{c.old}</td>
                    <td>→</td>
                    <td style={{ fontWeight: 700, color: "var(--primary)" }}>{c.next}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ display: "flex", gap: 10, marginTop: 18, justifyContent: "flex-end" }}>
              <button onClick={() => setStep("edit")} style={{ padding: "10px 18px", borderRadius: 10, border: "2px solid var(--border)", background: "var(--surface)" }}>
                ← {t("emps_back")}
              </button>
              <button
                data-testid="emp-confirm-btn"
                disabled={busy}
                onClick={save}
                style={{ padding: "10px 18px", borderRadius: 10, border: "none", fontWeight: 700, background: "var(--success)", color: "#fff" }}
              >
                {busy ? "…" : t("emps_confirm")}
              </button>
            </div>
          </>
        )}

        {step === "history" && (
          <>
            {history === null ? <Loading /> : history.length === 0 ? <Empty /> : (
              <div className="detail-rows" data-testid="emp-history-list" style={{ fontSize: 14 }}>
                {[...history].reverse().map((h, i) => (
                  <div key={i} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
                    <b>{h.action.replace("employee.", "")}</b>
                    {" — "}{new Date(h.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}
                    {h.by ? ` · ${h.by}` : ""}
                    {h.detail && Object.entries(h.detail).map(([k, v]: [string, any]) =>
                      v && typeof v === "object" && "new" in v ? (
                        <div key={k} style={{ color: "var(--muted)" }}>
                          {k}: {String(v.old ?? "—")} → <b style={{ color: "var(--text)" }}>{String(v.new)}</b>
                        </div>
                      ) : null,
                    )}
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", marginTop: 14, justifyContent: "flex-end" }}>
              <button onClick={() => setStep("edit")} style={{ padding: "10px 18px", borderRadius: 10, border: "2px solid var(--border)", background: "var(--surface)" }}>
                ← {t("emps_back")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Employees() {
  const { t, lang } = useI18n();
  const [rows, setRows] = useState<Emp[] | null>(null);
  const [depts, setDepts] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [dept, setDept] = useState("");
  const [err, setErr] = useState("");
  const [sel, setSel] = useState<Emp | null>(null);
  const [savedMsg, setSavedMsg] = useState(false);

  const load = () => api("/admin/employees?all=true").then(setRows).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api("/departments").then(setDepts).catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    if (!rows) return null;
    const needle = q.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (!dept || r.department_code === dept) &&
        (!needle ||
          r.full_name.toLowerCase().includes(needle) ||
          r.emp_id.toLowerCase().includes(needle) ||
          (r.phone ?? "").replace("+91", "").includes(needle.replace("+91", ""))),
    );
  }, [rows, q, dept]);

  const onSaved = () => {
    setSel(null);
    setSavedMsg(true);
    setTimeout(() => setSavedMsg(false), 2500);
    load();
  };

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="employees-title">{t("nav_employees")}</h1>
        <div style={{ display: "flex", gap: 10, marginRight: 150, alignItems: "center" }}>
          {savedMsg && <Chip tone="green">{t("emps_saved")}</Chip>}
          <select data-testid="emps-dept-filter" value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">{t("emps_all_depts")}</option>
            {depts.map((d) => <option key={d.code} value={d.code}>{localName(d, lang)}</option>)}
          </select>
        </div>
      </div>

      <input
        data-testid="emps-search"
        placeholder={`🔍 ${t("emps_search")}`}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: "100%", boxSizing: "border-box", marginBottom: 14, fontSize: 16 }}
      />

      {err && <div className="card" style={{ color: "var(--danger)" }}>{err}</div>}
      {!filtered ? (!err && <Loading />) : (
        <div className="card">
          <h2>{filtered.length} {t("employees")}</h2>
          {filtered.length === 0 ? <Empty /> : (
            <table data-testid="employees-table">
              <thead>
                <tr>
                  <th>{t("empId")}</th><th>{t("name")}</th><th>{t("department")}</th>
                  <th>{t("emps_role")}</th><th>{t("emps_phone")}</th><th>{t("emps_status")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((e) => (
                  <tr
                    key={e.id}
                    data-testid={`emp-row-${e.emp_id}`}
                    onClick={() => setSel(e)}
                    style={{ cursor: "pointer" }}
                    title={t("emps_edit")}
                  >
                    <td style={{ fontWeight: 700 }}>{e.emp_id}</td>
                    <td>{e.full_name}</td>
                    <td>{e.department_code ?? "—"}</td>
                    <td>{e.role_code}</td>
                    <td>{e.phone ?? "—"}</td>
                    <td><StatusChip e={e} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {sel && <Editor emp={sel} depts={depts} onClose={() => setSel(null)} onSaved={onSaved} />}
    </div>
  );
}
