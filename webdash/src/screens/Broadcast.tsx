import React, { useEffect, useMemo, useState } from "react";

import { api, ApiError, apiDownload } from "../api";
import { Chip, Empty, Loading } from "../components";
import { localName, useI18n } from "../i18n";

type Meta = { enabled: boolean; rate_per_hour: number; zones: string[] };
type RoleOpt = { code: string; rank: number; label_en: string; label_hi: string; label_mr: string; assignable: boolean };
type Dept = { code: string; name_en: string; name_hi: string; name_mr: string };
type EmpLite = { id: string; emp_id: string; full_name: string; department_code: string | null };
type AudType = "all" | "department" | "role" | "designation" | "zone" | "employees";
type Priority = "normal" | "important" | "emergency";

type BroadcastRow = {
  id: string; created_by_name: string | null; audience_type: string; audience_json: any;
  title_en: string; title_hi: string; title_mr: string;
  body_en: string; body_hi: string; body_mr: string;
  priority: Priority; status: string; scheduled_at: string | null; sent_at: string | null; created_at: string | null;
  recipient_count: number; installed_count: number; sent_count: number; delivered_count: number;
  failed_count: number; no_token_count: number; suppressed_count: number; opened_count: number;
  failed_recipients?: { emp_id: string; name: string; department_code: string | null; status: string; error: string | null }[];
};

type Template = {
  id: string; is_builtin: boolean; priority: Priority;
  title_en: string; title_hi: string; title_mr: string;
  body_en: string; body_hi: string; body_mr: string;
};

type Receipt = {
  emp_id: string; name: string; department_code: string | null;
  status: string; error: string | null; updated_at: string | null;
};

const PRIO_TONE: Record<Priority, "green" | "amber" | "red"> = { normal: "green", important: "amber", emergency: "red" };
const PRIO_EMOJI: Record<Priority, string> = { normal: "📢", important: "❗", emergency: "🚨" };
const STATUS_KEY: Record<string, string> = {
  opened: "bc_status_opened", delivered: "bc_status_delivered", sent: "bc_status_sent",
  failed: "bc_status_failed", no_token: "bc_status_no_token", suppressed: "bc_status_suppressed", queued: "bc_status_queued",
};
const STATUS_TONE: Record<string, "green" | "amber" | "red"> = {
  opened: "green", delivered: "green", sent: "amber", suppressed: "amber", queued: "amber", failed: "red", no_token: "red",
};
const roleLabel = (r: RoleOpt, lang: string) => (r as any)[`label_${lang}`] || r.label_en;
const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

export default function Broadcast() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"compose" | "history">("compose");
  return (
    <div>
      <div className="topbar">
        <h1 data-testid="broadcast-title">{t("nav_broadcast")}</h1>
        <div style={{ display: "flex", gap: 8, marginRight: 150 }}>
          <button className={`btn ${tab === "compose" ? "primary" : "ghost"}`} data-testid="bc-tab-compose" onClick={() => setTab("compose")}>{t("bc_tab_compose")}</button>
          <button className={`btn ${tab === "history" ? "primary" : "ghost"}`} data-testid="bc-tab-history" onClick={() => setTab("history")}>{t("bc_tab_history")}</button>
        </div>
      </div>
      {tab === "compose" ? <Compose goHistory={() => setTab("history")} /> : <History />}
    </div>
  );
}

function Compose({ goHistory }: { goHistory: () => void }) {
  const { t, lang } = useI18n();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [depts, setDepts] = useState<Dept[]>([]);
  const [roles, setRoles] = useState<RoleOpt[]>([]);
  const [desigs, setDesigs] = useState<string[]>([]);

  const [audType, setAudType] = useState<AudType>("all");
  const [selDepts, setSelDepts] = useState<string[]>([]);
  const [selRoles, setSelRoles] = useState<string[]>([]);
  const [selDesigs, setSelDesigs] = useState<string[]>([]);
  const [selZones, setSelZones] = useState<string[]>([]);
  const [empQuery, setEmpQuery] = useState("");
  const [empResults, setEmpResults] = useState<EmpLite[]>([]);
  const [selEmps, setSelEmps] = useState<EmpLite[]>([]);

  const [tLang, setTLang] = useState<"mr" | "hi" | "en">("mr");
  const [title, setTitle] = useState({ mr: "", hi: "", en: "" });
  const [body, setBody] = useState({ mr: "", hi: "", en: "" });
  const [priority, setPriority] = useState<Priority>("normal");
  const [dlType, setDlType] = useState("");
  const [dlId, setDlId] = useState("");
  const [when, setWhen] = useState<"now" | "schedule">("now");
  const [schedAt, setSchedAt] = useState("");

  const [preview, setPreview] = useState<{ recipient_count: number; installed_count: number; no_token_count: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [dupWarn, setDupWarn] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [editingTpl, setEditingTpl] = useState<Template | null>(null);

  useEffect(() => {
    api("/broadcasts/meta").then(setMeta).catch(() => {});
    api("/departments").then(setDepts).catch(() => {});
    api("/admin/roles").then((r) => setRoles(r.roles || [])).catch(() => {});
    api("/admin/designations").then((r) => setDesigs(r.designations || [])).catch(() => {});
    api("/broadcasts/templates").then((r) => setTemplates(r.items || [])).catch(() => {});
  }, []);

  // employee search (debounced)
  useEffect(() => {
    if (audType !== "employees" || empQuery.trim().length < 2) { setEmpResults([]); return; }
    const h = setTimeout(() => {
      api(`/admin/employees?search=${encodeURIComponent(empQuery.trim())}`).then(setEmpResults).catch(() => {});
    }, 300);
    return () => clearTimeout(h);
  }, [empQuery, audType]);

  const audiencePayload = useMemo(() => {
    const base: any = { audience_type: audType };
    if (audType === "department") base.departments = selDepts;
    if (audType === "role") base.roles = selRoles;
    if (audType === "designation") base.designations = selDesigs;
    if (audType === "zone") base.zones = selZones;
    if (audType === "employees") base.employee_ids = selEmps.map((e) => e.id);
    return base;
  }, [audType, selDepts, selRoles, selDesigs, selZones, selEmps]);

  const audienceReady = audType === "all" ||
    (audType === "department" && selDepts.length > 0) ||
    (audType === "role" && selRoles.length > 0) ||
    (audType === "designation" && selDesigs.length > 0) ||
    (audType === "zone" && selZones.length > 0) ||
    (audType === "employees" && selEmps.length > 0);

  // live recipient count
  useEffect(() => {
    if (!audienceReady) { setPreview(null); return; }
    const h = setTimeout(() => {
      api("/broadcasts/preview", { method: "POST", body: JSON.stringify(audiencePayload) })
        .then(setPreview).catch(() => setPreview(null));
    }, 250);
    return () => clearTimeout(h);
  }, [audiencePayload, audienceReady]);

  const contentReady = (title.mr || title.en || title.hi).trim() !== "" && (body.mr || body.en || body.hi).trim() !== "";
  const canSend = audienceReady && contentReady && (when === "now" || schedAt !== "");

  const toggle = (arr: string[], set: (v: string[]) => void, v: string) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const composePayload = (force = false) => ({
    ...audiencePayload,
    title_mr: title.mr, title_hi: title.hi, title_en: title.en,
    body_mr: body.mr, body_hi: body.hi, body_en: body.en,
    priority,
    ...(dlType ? { deep_link_type: dlType, ...(dlId.trim() ? { deep_link_id: dlId.trim() } : {}) } : {}),
    ...(when === "schedule" && schedAt ? { scheduled_at: new Date(schedAt).toISOString() } : {}),
    force,
  });

  const handleErr = (e: any) => {
    const s = e instanceof ApiError ? e.status : 0;
    if (s === 403) setErr(t("bc_disabled"));
    else if (s === 429) setErr(t("bc_rate_limited"));
    else if (s === 422) setErr(t("bc_no_recipients"));
    else if (s === 409) { setDupWarn(true); return; }
    else setErr(e.message || "error");
  };

  const doSend = async (force = false) => {
    setBusy(true); setErr(""); setMsg(""); setDupWarn(false);
    try {
      const r = await api("/broadcasts", { method: "POST", body: JSON.stringify(composePayload(force)) });
      setConfirm(false);
      setMsg(r.status === "scheduled" ? t("bc_scheduled_ok") : t("bc_sent_ok"));
      setTitle({ mr: "", hi: "", en: "" }); setBody({ mr: "", hi: "", en: "" });
      setTimeout(goHistory, 900);
    } catch (e) { setConfirm(false); handleErr(e); }
    finally { setBusy(false); }
  };

  const sendTest = async () => {
    setBusy(true); setErr(""); setMsg("");
    try {
      await api("/broadcasts/test", { method: "POST", body: JSON.stringify(composePayload()) });
      setMsg(t("bc_test_sent"));
    } catch (e: any) { handleErr(e); }
    finally { setBusy(false); }
  };

  const applyTemplate = (tpl: Template) => {
    setTitle({ mr: tpl.title_mr, hi: tpl.title_hi, en: tpl.title_en });
    setBody({ mr: tpl.body_mr, hi: tpl.body_hi, en: tpl.body_en });
    setPriority(tpl.priority);
    setErr(""); setMsg("");
  };

  const startEdit = (tpl: Template) => {
    applyTemplate(tpl);
    setEditingTpl(tpl);
  };

  const cancelEdit = () => setEditingTpl(null);

  const saveTemplate = async () => {
    setBusy(true); setErr(""); setMsg("");
    const payload = {
      title_mr: title.mr, title_hi: title.hi, title_en: title.en,
      body_mr: body.mr, body_hi: body.hi, body_en: body.en, priority,
    };
    try {
      if (editingTpl) {
        await api(`/broadcasts/templates/${editingTpl.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        setMsg(t("bc_template_updated"));
        setEditingTpl(null);
      } else {
        await api("/broadcasts/templates", { method: "POST", body: JSON.stringify(payload) });
        setMsg(t("bc_template_saved"));
      }
      const r = await api("/broadcasts/templates");
      setTemplates(r.items || []);
    } catch (e: any) { handleErr(e); }
    finally { setBusy(false); }
  };

  const deleteTemplate = async (id: string) => {
    if (!window.confirm(t("bc_template_delete_confirm"))) return;
    try {
      await api(`/broadcasts/templates/${id}`, { method: "DELETE" });
      setTemplates((prev) => prev.filter((x) => x.id !== id));
      if (editingTpl?.id === id) setEditingTpl(null);
    } catch { /* best effort */ }
  };

  if (!meta) return <Loading />;

  const audBtn = (v: AudType, label: string) => (
    <button key={v} data-testid={`bc-aud-${v}`} onClick={() => setAudType(v)}
      className={`btn ${audType === v ? "primary" : "ghost"}`} style={{ fontSize: 14 }}>{label}</button>
  );
  const sectionStyle: React.CSSProperties = { marginTop: 16 };
  const label: React.CSSProperties = { fontWeight: 700, fontSize: 14, margin: "4px 0 6px" };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 300px", gap: 20 }} className="bc-grid">
      <div>
        {!meta.enabled && (
          <div className="card" data-testid="bc-disabled-note" style={{ background: "#FFF4E5", borderColor: "#E0A800" }}>
            ⚠️ {t("bc_disabled")}
          </div>
        )}

        <div className="card" data-testid="bc-templates">
          <div style={label}>⚡ {t("bc_templates")}</div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginBottom: 8 }}>{t("bc_templates_hint")}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {templates.map((tpl) => {
              const lbl = (tpl as any)[`title_${lang}`] || tpl.title_mr || tpl.title_en;
              const isEditing = editingTpl?.id === tpl.id;
              return (
                <span key={tpl.id} data-testid={`bc-tpl-${tpl.id}`}
                  className={`btn ${isEditing ? "primary" : "ghost"}`}
                  style={{ fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer" }}
                  onClick={() => applyTemplate(tpl)}>
                  <span>{PRIO_EMOJI[tpl.priority]} {lbl}</span>
                  {!tpl.is_builtin && (
                    <>
                      <span data-testid={`bc-tpl-edit-${tpl.id}`} aria-label="edit template"
                        onClick={(e) => { e.stopPropagation(); startEdit(tpl); }}
                        style={{ marginLeft: 2 }}>✎</span>
                      <span data-testid={`bc-tpl-del-${tpl.id}`} aria-label="delete template"
                        onClick={(e) => { e.stopPropagation(); deleteTemplate(tpl.id); }}
                        style={{ color: "var(--danger)", fontWeight: 700, marginLeft: 2 }}>✕</span>
                    </>
                  )}
                </span>
              );
            })}
          </div>
        </div>

        <div className="card">
          <div style={label}>{t("bc_audience")}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {audBtn("all", t("bc_aud_all"))}
            {audBtn("department", t("bc_aud_department"))}
            {audBtn("role", t("bc_aud_role"))}
            {audBtn("designation", t("bc_aud_designation"))}
            {audBtn("zone", t("bc_aud_zone"))}
            {audBtn("employees", t("bc_aud_employees"))}
          </div>

          {audType === "department" && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }} data-testid="bc-dept-list">
              {depts.map((d) => (
                <button key={d.code} onClick={() => toggle(selDepts, setSelDepts, d.code)}
                  className={`btn ${selDepts.includes(d.code) ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>
                  {localName(d, lang)}
                </button>
              ))}
            </div>
          )}
          {audType === "role" && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }} data-testid="bc-role-list">
              {roles.map((r) => (
                <button key={r.code} onClick={() => toggle(selRoles, setSelRoles, r.code)}
                  className={`btn ${selRoles.includes(r.code) ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>
                  {roleLabel(r, lang)}
                </button>
              ))}
            </div>
          )}
          {audType === "designation" && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12, maxHeight: 180, overflowY: "auto" }} data-testid="bc-desig-list">
              {desigs.map((d) => (
                <button key={d} onClick={() => toggle(selDesigs, setSelDesigs, d)}
                  className={`btn ${selDesigs.includes(d) ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>{d}</button>
              ))}
            </div>
          )}
          {audType === "zone" && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12, maxHeight: 180, overflowY: "auto" }} data-testid="bc-zone-list">
              {meta.zones.map((z) => (
                <button key={z} onClick={() => toggle(selZones, setSelZones, z)}
                  className={`btn ${selZones.includes(z) ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>{z}</button>
              ))}
            </div>
          )}
          {audType === "employees" && (
            <div style={{ marginTop: 12 }}>
              <input data-testid="bc-emp-search" placeholder={t("bc_search_people")} value={empQuery}
                onChange={(e) => setEmpQuery(e.target.value)} style={{ width: "100%", boxSizing: "border-box" }} />
              {selEmps.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                  {selEmps.map((e) => (
                    <span key={e.id} onClick={() => setSelEmps(selEmps.filter((x) => x.id !== e.id))}
                      style={{ cursor: "pointer", background: "var(--brand-tertiary,#EAF1FB)", padding: "4px 10px", borderRadius: 14, fontSize: 13 }}>
                      {e.full_name} ✕
                    </span>
                  ))}
                </div>
              )}
              {empResults.length > 0 && (
                <div style={{ marginTop: 8, border: "1px solid var(--border)", borderRadius: 8, maxHeight: 160, overflowY: "auto" }}>
                  {empResults.filter((e) => !selEmps.some((s) => s.id === e.id)).map((e) => (
                    <div key={e.id} data-testid={`bc-emp-opt-${e.emp_id}`} onClick={() => { setSelEmps([...selEmps, e]); setEmpQuery(""); setEmpResults([]); }}
                      style={{ padding: "8px 10px", cursor: "pointer", borderBottom: "1px solid var(--border)" }}>
                      {e.full_name} <span style={{ color: "var(--muted)" }}>#{e.emp_id} · {e.department_code || "—"}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div data-testid="bc-recipient-count" style={{ marginTop: 14, fontWeight: 600, fontSize: 15 }}>
            {audienceReady && preview ? (
              <span>👥 {t("bc_will_reach")} <b>{preview.recipient_count}</b> · {preview.installed_count} {t("bc_have_app")}
                {preview.no_token_count > 0 ? <span style={{ color: "var(--muted)", fontWeight: 400 }}> · {preview.no_token_count} {t("bc_no_token")}</span> : null}</span>
            ) : <span style={{ color: "var(--muted)", fontWeight: 400 }}>{t("bc_pick_some")}</span>}
          </div>
        </div>

        <div className="card" style={sectionStyle}>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            {(["mr", "hi", "en"] as const).map((l) => (
              <button key={l} data-testid={`bc-lang-${l}`} onClick={() => setTLang(l)}
                className={`btn ${tLang === l ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>
                {l === "mr" ? "मराठी" : l === "hi" ? "हिंदी" : "English"}
              </button>
            ))}
          </div>
          <div style={label}>{t("bc_title_label")}</div>
          <input data-testid="bc-title-input" value={title[tLang]} maxLength={120}
            onChange={(e) => setTitle({ ...title, [tLang]: e.target.value })} style={{ width: "100%", boxSizing: "border-box" }} />
          <div style={label}>{t("bc_message_label")}</div>
          <textarea data-testid="bc-body-input" value={body[tLang]} rows={4} maxLength={1000}
            onChange={(e) => setBody({ ...body, [tLang]: e.target.value })} style={{ width: "100%", boxSizing: "border-box" }} />
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 6 }}>{t("bc_marathi_note")}</div>
        </div>

        <div className="card" style={sectionStyle}>
          <div style={label}>{t("bc_priority")}</div>
          <div style={{ display: "flex", gap: 8 }}>
            {(["normal", "important", "emergency"] as Priority[]).map((p) => (
              <button key={p} data-testid={`bc-prio-${p}`} onClick={() => setPriority(p)}
                className={`btn ${priority === p ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>
                {t(`bc_prio_${p}`)}
              </button>
            ))}
          </div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 6 }}>{t("bc_prio_note")}</div>

          <div style={{ ...label, marginTop: 14 }}>{t("bc_deeplink")}</div>
          <select data-testid="bc-deeplink" value={dlType} onChange={(e) => setDlType(e.target.value)} style={{ width: "100%", boxSizing: "border-box" }}>
            <option value="">{t("bc_dl_none")}</option>
            <option value="incident">{t("bc_dl_incident")}</option>
            <option value="employee">{t("bc_dl_approval")}</option>
            <option value="vehicle">{t("bc_dl_vehicle")}</option>
          </select>
          {dlType === "incident" && (
            <input data-testid="bc-deeplink-id" placeholder={t("bc_dl_id")} value={dlId} onChange={(e) => setDlId(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box", marginTop: 8 }} />
          )}

          <div style={{ ...label, marginTop: 14 }}>{t("bc_when")}</div>
          <div style={{ display: "flex", gap: 8 }}>
            <button data-testid="bc-when-now" onClick={() => setWhen("now")} className={`btn ${when === "now" ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>{t("bc_send_now")}</button>
            <button data-testid="bc-when-schedule" onClick={() => setWhen("schedule")} className={`btn ${when === "schedule" ? "primary" : "ghost"}`} style={{ fontSize: 13 }}>{t("bc_schedule")}</button>
          </div>
          {when === "schedule" && (
            <>
              <div style={{ ...label, marginTop: 10 }}>{t("bc_schedule_at")}</div>
              <input data-testid="bc-sched-at" type="datetime-local" value={schedAt} onChange={(e) => setSchedAt(e.target.value)}
                style={{ width: "100%", boxSizing: "border-box" }} />
            </>
          )}
        </div>

        {err && <div className="card" data-testid="bc-error" style={{ color: "var(--danger)", fontWeight: 600 }}>{err}</div>}
        {msg && <div className="card" data-testid="bc-success" style={{ color: "var(--success)", fontWeight: 700 }}>{msg}</div>}
        {dupWarn && (
          <div className="card" data-testid="bc-dup-warn" style={{ background: "#FFF4E5", borderColor: "#E0A800" }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>⚠️ {t("bc_duplicate_warn")}</div>
            <button className="btn primary" data-testid="bc-send-anyway" disabled={busy} onClick={() => doSend(true)}>{t("bc_send_anyway")}</button>
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn ghost" data-testid="bc-send-test" disabled={busy || !contentReady} onClick={sendTest}>🧪 {t("bc_send_test")}</button>
          <button className="btn ghost" data-testid="bc-save-template" disabled={busy || !contentReady} onClick={saveTemplate}>
            {editingTpl ? `✏️ ${t("bc_update_template")}` : `💾 ${t("bc_save_template")}`}
          </button>
          {editingTpl && (
            <button className="btn ghost" data-testid="bc-cancel-edit" disabled={busy} onClick={cancelEdit}
              style={{ color: "var(--muted)" }}>{t("bc_cancel_edit")}</button>
          )}
          <button className="btn primary" data-testid="bc-review-send" disabled={busy || !canSend} onClick={() => setConfirm(true)}>
            {when === "schedule" ? t("bc_schedule_btn") : t("bc_review_send")}
          </button>
        </div>
      </div>

      {/* phone preview */}
      <div>
        <div style={{ ...label, textAlign: "center" }}>{t("bc_preview")}</div>
        <div data-testid="bc-preview" style={{ margin: "0 auto", width: 260, border: "10px solid #111", borderRadius: 28, background: "#f1f1f4", minHeight: 160, padding: 14 }}>
          <div style={{ background: "#fff", borderRadius: 14, padding: 12, boxShadow: "0 2px 6px rgba(0,0,0,0.12)" }}>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>HogoPlus-FS · now</div>
            <div style={{ fontWeight: 700, fontSize: 14 }}>
              {priority === "emergency" ? "🚨 " : priority === "important" ? "❗ " : "📢 "}
              {(title[tLang] || title.mr || t("bc_title_label"))}
            </div>
            <div style={{ fontSize: 13, color: "#333", marginTop: 4, whiteSpace: "pre-wrap" }}>
              {body[tLang] || body.mr || ""}
            </div>
          </div>
        </div>
      </div>

      {confirm && (
        <div className="modal-backdrop" onClick={() => setConfirm(false)}>
          <div className="modal-card" data-testid="bc-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <h2 style={{ color: "var(--primary)" }}>{t("bc_confirm_title")}</h2>
            <p style={{ fontSize: 15 }}>
              {t("bc_confirm_body")} <b>{preview?.recipient_count ?? 0}</b> · {preview?.installed_count ?? 0} {t("bc_have_app")}
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 14 }}>
              <button className="btn ghost" onClick={() => setConfirm(false)}>{t("bc_cancel")}</button>
              <button className="btn primary" data-testid="bc-confirm-send" disabled={busy} onClick={() => doSend(false)}>
                {busy ? "…" : t("bc_confirm_send")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function History() {
  const { t, lang } = useI18n();
  const [rows, setRows] = useState<BroadcastRow[] | null>(null);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [sel, setSel] = useState<BroadcastRow | null>(null);
  const [err, setErr] = useState("");

  const load = () => {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (type) p.set("type", type);
    api(`/broadcasts?${p.toString()}`).then((r) => setRows(r.items)).catch((e) => setErr(e.message));
  };
  useEffect(() => { const h = setTimeout(load, 250); return () => clearTimeout(h); }, [q, type]);

  if (err) return <div className="card" style={{ color: "var(--danger)" }}>{err}</div>;
  if (!rows) return <Loading />;

  const tl = (r: BroadcastRow) => (r as any)[`title_${lang}`] || r.title_mr || r.title_en;

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <input data-testid="bc-hist-search" placeholder={`🔍 ${t("bc_tab_history")}`} value={q} onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1, minWidth: 180, boxSizing: "border-box" }} />
        <select data-testid="bc-hist-type" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">{t("bc_all_types")}</option>
          <option value="normal">{t("bc_prio_normal")}</option>
          <option value="important">{t("bc_prio_important")}</option>
          <option value="emergency">{t("bc_prio_emergency")}</option>
        </select>
      </div>
      {rows.length === 0 ? <div className="card"><Empty /><div style={{ textAlign: "center", color: "var(--muted)" }}>{t("bc_no_history")}</div></div> : (
        <div className="card" style={{ padding: 0 }}>
          {rows.map((r) => (
            <div key={r.id} data-testid={`bc-hist-${r.id}`} onClick={() => setSel(r)}
              style={{ padding: 14, borderBottom: "1px solid var(--border)", cursor: "pointer" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
                <div style={{ fontWeight: 700 }}>{tl(r)}</div>
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {r.status === "scheduled" && <Chip tone="amber">{t("bc_scheduled_badge")}</Chip>}
                  <Chip tone={PRIO_TONE[r.priority]}>{t(`bc_prio_${r.priority}`)}</Chip>
                </div>
              </div>
              <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>
                {t("bc_sender")}: {r.created_by_name || "—"} · {fmt(r.scheduled_at || r.sent_at || r.created_at)} · 👥 {r.recipient_count}
              </div>
              <div style={{ fontSize: 13, marginTop: 6, display: "flex", gap: 10, flexWrap: "wrap" }}>
                <span>✅ {t("bc_delivered")} {r.delivered_count}</span>
                <span>📤 {t("bc_sent")} {r.sent_count}</span>
                <span style={{ color: "var(--danger)" }}>⚠️ {t("bc_failed")} {r.failed_count}</span>
                <span style={{ color: "var(--muted)" }}>📵 {r.no_token_count}</span>
                <span>👁 {t("bc_opened")} {r.opened_count}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {sel && <DetailModal row={sel} onClose={() => setSel(null)} onChanged={() => { setSel(null); load(); }} />}
    </div>
  );
}

function DetailModal({ row, onClose, onChanged }: { row: BroadcastRow; onClose: () => void; onChanged: () => void }) {
  const { t, lang } = useI18n();
  const [full, setFull] = useState<BroadcastRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showReceipts, setShowReceipts] = useState(false);
  const [receipts, setReceipts] = useState<Receipt[] | null>(null);
  const [rFilter, setRFilter] = useState<string>("");

  useEffect(() => { api(`/broadcasts/${row.id}`).then(setFull).catch((e) => setErr(e.message)); }, [row.id]);

  const loadReceipts = (status: string) => {
    setRFilter(status);
    setReceipts(null);
    const qs = status ? `?status=${status}` : "";
    api(`/broadcasts/${row.id}/receipts${qs}`).then((d) => setReceipts(d.items || [])).catch(() => setReceipts([]));
  };

  const toggleReceipts = () => {
    const next = !showReceipts;
    setShowReceipts(next);
    if (next && receipts === null) loadReceipts("");
  };

  const resend = async (failedOnly: boolean) => {
    setBusy(true); setErr("");
    try {
      await api(`/broadcasts/${row.id}/resend`, { method: "POST", body: JSON.stringify({ failed_only: failedOnly }) });
      onChanged();
    } catch (e: any) { setErr(e.status === 403 ? t("bc_disabled") : e.message); }
    finally { setBusy(false); }
  };

  const r = full || row;
  const tl = (r as any)[`title_${lang}`] || r.title_mr || r.title_en;
  const bl = (r as any)[`body_${lang}`] || r.body_mr || r.body_en;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" data-testid="bc-detail-modal" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ color: "var(--primary)" }}>{tl}</h2>
          <button onClick={onClose} aria-label="close">✕</button>
        </div>
        <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("bc_sender")}: {r.created_by_name || "—"} · {fmt(r.sent_at || r.created_at)}</div>
        <p style={{ whiteSpace: "pre-wrap", marginTop: 8 }}>{bl}</p>
        <div className="card" style={{ marginTop: 10 }}>
          <b>{t("bc_delivery")}</b>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 8, fontSize: 14 }}>
            <span>👥 {r.recipient_count}</span>
            <span>✅ {t("bc_delivered")} {r.delivered_count}</span>
            <span>📤 {t("bc_sent")} {r.sent_count}</span>
            <span style={{ color: "var(--danger)" }}>⚠️ {t("bc_failed")} {r.failed_count}</span>
            <span style={{ color: "var(--muted)" }}>📵 {r.no_token_count} ({t("bc_no_token")})</span>
            <span>🔕 {t("bc_suppressed")} {r.suppressed_count}</span>
            <span>👁 {t("bc_opened")} {r.opened_count}</span>
          </div>
        </div>
        {full?.failed_recipients && full.failed_recipients.length > 0 && (
          <div style={{ marginTop: 10, maxHeight: 180, overflowY: "auto" }} data-testid="bc-failed-list">
            <b>{t("bc_failed_list")}</b>
            {full.failed_recipients.map((f) => (
              <div key={f.emp_id} style={{ fontSize: 13, padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
                {f.name} <span style={{ color: "var(--muted)" }}>#{f.emp_id} · {f.status}{f.error ? ` · ${f.error}` : ""}</span>
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: 12 }}>
          <button className="btn ghost" data-testid="bc-view-receipts" onClick={toggleReceipts}>
            📋 {showReceipts ? t("bc_hide_receipts") : t("bc_view_receipts")}
          </button>
        </div>
        {showReceipts && (
          <div className="card" data-testid="bc-receipts-panel" style={{ marginTop: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
              <b>{t("bc_receipts")}</b>
              <button className="btn ghost" data-testid="bc-export-xlsx" style={{ fontSize: 12 }}
                onClick={() => apiDownload(`/broadcasts/${row.id}/receipts.xlsx`, `broadcast_delivery_${row.id.slice(0, 8)}.xlsx`).catch(() => {})}>
                ⬇️ {t("bc_export_xlsx")}
              </button>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "8px 0" }}>
              {([
                ["", t("bc_receipts_all"), r.recipient_count],
                ["delivered", t("bc_status_delivered"), r.delivered_count],
                ["opened", t("bc_status_opened"), r.opened_count],
                ["sent", t("bc_status_sent"), r.sent_count],
                ["failed", t("bc_status_failed"), r.failed_count],
                ["no_token", t("bc_status_no_token"), r.no_token_count],
                ["suppressed", t("bc_status_suppressed"), r.suppressed_count],
              ] as [string, string, number][]).map(([st, lbl, n]) => (
                <button key={st || "all"} data-testid={`bc-rfilter-${st || "all"}`}
                  className={`btn ${rFilter === st ? "primary" : "ghost"}`} style={{ fontSize: 12 }}
                  onClick={() => loadReceipts(st)}>
                  {lbl} ({n})
                </button>
              ))}
            </div>
            {receipts === null ? <Loading /> : receipts.length === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13, padding: "6px 0" }}>{t("bc_no_receipts")}</div>
            ) : (
              <div data-testid="bc-receipts-list" style={{ maxHeight: 260, overflowY: "auto" }}>
                {receipts.map((rc) => (
                  <div key={rc.emp_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, fontSize: 13, padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                    <span>{rc.name} <span style={{ color: "var(--muted)" }}>#{rc.emp_id} · {rc.department_code || "—"}</span></span>
                    <Chip tone={STATUS_TONE[rc.status] || "amber"}>{t(STATUS_KEY[rc.status] || "bc_status_queued")}</Chip>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {err && <div style={{ color: "var(--danger)", fontWeight: 600, marginTop: 8 }}>{err}</div>}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 14 }}>
          <button className="btn ghost" data-testid="bc-resend-failed" disabled={busy} onClick={() => resend(true)}>{t("bc_resend_failed")}</button>
          <button className="btn primary" data-testid="bc-resend-all" disabled={busy} onClick={() => resend(false)}>{t("bc_resend")}</button>
        </div>
      </div>
    </div>
  );
}
