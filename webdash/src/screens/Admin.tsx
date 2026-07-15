import React, { useEffect, useState } from "react";
import { api } from "../api";
import { isTopMgmt, useAuth } from "../auth";
import { Chip, Empty } from "../components";
import { localName, useI18n } from "../i18n";

const ROLES = ["MD", "CGM", "Manager", "Staff", "Clerk", "Worker"];

function EmployeeSearch({ render }: { render: (e: any, reload: () => void) => React.ReactNode }) {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const search = () => {
    if (q.trim().length < 2) return;
    api(`/admin/employees?search=${encodeURIComponent(q.trim())}`).then(setRows).catch(() => setRows([]));
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input style={{ flex: 1 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")} onKeyDown={(e) => e.key === "Enter" && search()} />
        <button className="btn primary" onClick={search}>🔍</button>
      </div>
      {rows.map((e) => (
        <div key={e.id} className="feed-item" style={{ cursor: "default" }}>
          <div style={{ flex: 1 }}>
            <div className="t">{e.full_name} <span style={{ color: "var(--muted)", fontWeight: 400 }}>#{e.emp_id}</span></div>
            <div className="m">{e.department_code} · {e.role_code} · {e.phone || t("missingPhones")}</div>
          </div>
          {render(e, search)}
        </div>
      ))}
    </div>
  );
}

export default function Admin() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const [geo, setGeo] = useState<any>(null);
  const [geoMsg, setGeoMsg] = useState("");
  const [depts, setDepts] = useState<any[]>([]);
  const [targetDept, setTargetDept] = useState("");
  const [assignMsg, setAssignMsg] = useState("");
  const [noPhone, setNoPhone] = useState<any[]>([]);
  const [phoneEdits, setPhoneEdits] = useState<Record<string, string>>({});
  const [roleEdits, setRoleEdits] = useState<Record<string, string>>({});
  const [sops, setSops] = useState<any[] | null>(null);
  const [opsMsg, setOpsMsg] = useState("");

  const loadDepts = () => api("/departments").then((d) => { setDepts(d); if (!targetDept && d.length) setTargetDept(d[0].code); });
  const loadNoPhone = () => api("/admin/employees?missing_phone=true").then(setNoPhone).catch(() => {});
  const loadSops = () => api("/admin/sop-docs").then(setSops).catch(() => setSops([]));

  useEffect(() => {
    api("/admin/settings").then(setGeo).catch(() => {});
    loadDepts();
    loadNoPhone();
    loadSops();
  }, []);

  if (!isTopMgmt(user)) return <div className="card">{t("accessDeniedMsg")}</div>;

  const saveGeo = async () => {
    setGeoMsg("");
    try {
      const res = await api("/admin/settings", {
        method: "PATCH",
        body: JSON.stringify({ factory_lat: Number(geo.factory_lat), factory_lng: Number(geo.factory_lng), radius_meters: Number(geo.radius_meters) }),
      });
      setGeo(res);
      setGeoMsg(`✓ ${t("saved")}`);
    } catch (e: any) {
      setGeoMsg(e.message);
    }
  };

  const assign = async (emp: any) => {
    setAssignMsg("");
    try {
      const r = await api(`/admin/departments/${targetDept}/assign-manager`, { method: "POST", body: JSON.stringify({ employee_id: emp.id }) });
      setAssignMsg(`✓ ${t("assigned")}: ${r.manager_name} → ${targetDept}`);
      loadDepts();
    } catch (e: any) {
      setAssignMsg(e.message);
    }
  };

  const savePhone = async (emp: any) => {
    const phone = phoneEdits[emp.id];
    if (!phone) return;
    try {
      await api(`/admin/employees/${emp.id}`, { method: "PATCH", body: JSON.stringify({ phone }) });
      loadNoPhone();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const saveRole = async (emp: any, reload: () => void) => {
    const role = roleEdits[emp.id];
    if (!role || role === emp.role_code) return;
    try {
      await api(`/admin/employees/${emp.id}`, { method: "PATCH", body: JSON.stringify({ role_code: role }) });
      reload();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const uploadSop = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api("/admin/sop-docs", { method: "POST", body: fd });
      loadSops();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const backupNow = async () => {
    setOpsMsg("");
    try {
      await api("/admin/backup-now", { method: "POST" });
      setOpsMsg(`✓ ${t("backupStarted")}`);
    } catch (e: any) {
      setOpsMsg(e.message);
    }
  };

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="admin-title">{t("nav_admin")}</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {opsMsg && <span style={{ fontSize: 13, color: "var(--muted)" }}>{opsMsg}</span>}
          <button className="btn ghost" data-testid="backup-now" onClick={backupNow}>💾 {t("backupNow")}</button>
        </div>
      </div>

      <div className="grid">
        <div>
          <div className="card">
            <h2>📍 {t("geofence")}</h2>
            {!geo ? <Empty /> : (
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
                <div><label style={{ fontSize: 13, color: "var(--muted)" }}>{t("lat")}</label><br />
                  <input data-testid="geo-lat" type="number" step="0.000001" value={geo.factory_lat} onChange={(e) => setGeo({ ...geo, factory_lat: e.target.value })} /></div>
                <div><label style={{ fontSize: 13, color: "var(--muted)" }}>{t("lng")}</label><br />
                  <input data-testid="geo-lng" type="number" step="0.000001" value={geo.factory_lng} onChange={(e) => setGeo({ ...geo, factory_lng: e.target.value })} /></div>
                <div><label style={{ fontSize: 13, color: "var(--muted)" }}>{t("radius")}</label><br />
                  <input data-testid="geo-radius" type="number" min={50} max={10000} value={geo.radius_meters} onChange={(e) => setGeo({ ...geo, radius_meters: e.target.value })} /></div>
                <button className="btn primary" data-testid="geo-save" onClick={saveGeo}>{t("save")}</button>
                {geoMsg && <span style={{ fontSize: 13, color: geoMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>{geoMsg}</span>}
              </div>
            )}
          </div>

          <div className="card">
            <h2>👔 {t("assignManager")}</h2>
            <div style={{ marginBottom: 10 }}>
              <select data-testid="assign-dept-select" value={targetDept} onChange={(e) => setTargetDept(e.target.value)}>
                {depts.map((d) => (
                  <option key={d.code} value={d.code}>{localName(d, lang)} {d.has_manager ? "✓" : "⚠"}</option>
                ))}
              </select>
              {assignMsg && <span style={{ marginLeft: 10, fontSize: 13, color: assignMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>{assignMsg}</span>}
            </div>
            <EmployeeSearch render={(e) => (
              <button className="btn primary" onClick={() => assign(e)}>{t("assign")} → {targetDept}</button>
            )} />
          </div>

          <div className="card">
            <h2>🎖 {t("changeRole")}</h2>
            <EmployeeSearch render={(e, reload) => (
              <div style={{ display: "flex", gap: 6 }}>
                <select value={roleEdits[e.id] || e.role_code} onChange={(ev) => setRoleEdits({ ...roleEdits, [e.id]: ev.target.value })}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <button className="btn primary" onClick={() => saveRole(e, reload)}>{t("apply")}</button>
              </div>
            )} />
          </div>
        </div>

        <div>
          <div className="card">
            <h2>📵 {t("missingPhones")} ({noPhone.length})</h2>
            {noPhone.length === 0 ? <Empty /> : noPhone.map((e) => (
              <div key={e.id} className="feed-item" style={{ cursor: "default" }}>
                <div style={{ flex: 1 }}>
                  <div className="t">{e.full_name} <span style={{ color: "var(--muted)", fontWeight: 400 }}>#{e.emp_id}</span></div>
                  <div className="m">{e.department_code} · {e.role_code}</div>
                </div>
                <input style={{ width: 160 }} placeholder="+91…" value={phoneEdits[e.id] || ""} onChange={(ev) => setPhoneEdits({ ...phoneEdits, [e.id]: ev.target.value })} />
                <button className="btn success" onClick={() => savePhone(e)}>{t("save")}</button>
              </div>
            ))}
          </div>

          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <h2 style={{ margin: 0 }}>📚 {t("sopDocs")}</h2>
              <label className="btn primary" style={{ display: "inline-block" }}>
                {t("upload")}
                <input type="file" accept="application/pdf" style={{ display: "none" }}
                  onChange={(e) => e.target.files?.[0] && uploadSop(e.target.files[0])} />
              </label>
            </div>
            {sops === null ? <div style={{ color: "var(--muted)" }}>{t("loading")}</div> : sops.length === 0 ? <Empty /> : sops.map((d) => (
              <div key={d.id} className="feed-item" style={{ cursor: "default" }}>
                <div style={{ flex: 1 }}>
                  <div className="t">{d.title}</div>
                  <div className="m">{d.page_count || 0} {t("pages")} · {d.chunk_count || 0} {t("chunks")}</div>
                </div>
                <Chip tone={d.status === "ready" ? "green" : d.status === "failed" ? "red" : "amber"}>{d.status}</Chip>
                <button className="btn danger" style={{ padding: "6px 10px" }} onClick={async () => { await api(`/admin/sop-docs/${d.id}`, { method: "DELETE" }); loadSops(); }}>✕</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
