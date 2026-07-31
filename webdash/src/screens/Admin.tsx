import React, { useEffect, useState } from "react";
import { api } from "../api";
import { isTopMgmt, useAuth } from "../auth";
import { Chip, Empty } from "../components";
import { localName, useI18n } from "../i18n";

const ROLES = ["MD", "CGM", "Manager", "Staff", "Clerk", "Worker"];
const MAC_RE = /^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$/;
const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

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
  const [beacons, setBeacons] = useState<any[]>([]);
  const [bMode, setBMode] = useState<"mac" | "ibeacon">("mac");
  const [bForm, setBForm] = useState({ mac: "", uuid: "", major: "", minor: "", en: "", hi: "", mr: "" });
  const [bMsg, setBMsg] = useState("");
  const [bulk, setBulk] = useState({ uuid: "", major: "1", dept: "", csv: "" });
  const [bulkMsg, setBulkMsg] = useState("");
  // App version & updates (2026-07-31: prod row was stuck at seeded 1.0.7 with a fake
  // apk_url because the ONLY way to change it was raw SQL — this card is the fix)
  const [ver, setVer] = useState<any>(null);
  const [verMsg, setVerMsg] = useState("");
  const [flagsMsg, setFlagsMsg] = useState("");

  const loadDepts = () => api("/departments").then((d) => { setDepts(d); if (!targetDept && d.length) setTargetDept(d[0].code); });
  const loadNoPhone = () => api("/admin/employees?missing_phone=true").then(setNoPhone).catch(() => {});
  const loadSops = () => api("/admin/sop-docs").then(setSops).catch(() => setSops([]));
  const loadBeacons = () => api("/admin/beacons").then(setBeacons).catch(() => setBeacons([]));

  useEffect(() => {
    api("/admin/settings").then(setGeo).catch(() => {});
    api("/app-version")
      .then((v) => setVer({ ...v, apk_url: v.apk_url ?? "", notes: v.notes ?? "", latest_version: v.latest_version ?? "" }))
      .catch(() => setVer({ latest_version: "", apk_url: "", notes: "", force_update: false }));
    loadDepts();
    loadNoPhone();
    loadSops();
    loadBeacons();
  }, []);

  if (!isTopMgmt(user)) return <div className="card">{t("accessDeniedMsg")}</div>;

  const saveVer = async () => {
    setVerMsg("");
    const v = (ver.latest_version || "").trim();
    if (!/^\d+\.\d+(\.\d+)?$/.test(v)) {
      setVerMsg(t("appver_bad_version"));
      return;
    }
    const url = (ver.apk_url || "").trim();
    if (url && !url.startsWith("https://")) {
      setVerMsg(t("appver_bad_url"));
      return;
    }
    // Distribution trap guard: force ON + no direct APK link = off-list phones
    // (outside Play internal testing) get the block screen with a dead-end URL.
    if (ver.force_update && (!url || url.includes("play.google.com"))) {
      if (!window.confirm(t("appver_force_confirm"))) return;
    }
    try {
      const res = await api("/admin/app-version", {
        method: "PUT",
        body: JSON.stringify({
          latest_version: v,
          apk_url: url || null,
          notes: (ver.notes || "").trim() || null,
          force_update: !!ver.force_update,
        }),
      });
      setVer({ ...res, apk_url: res.apk_url ?? "", notes: res.notes ?? "" });
      setVerMsg(`✓ ${t("saved")}`);
    } catch (e: any) {
      setVerMsg(e.message);
    }
  };

  const saveFlags = async () => {
    setFlagsMsg("");
    try {
      const res = await api("/admin/settings", {
        method: "PATCH",
        body: JSON.stringify({
          vehicle_log_enabled: !!geo.vehicle_log_enabled,
          home_config_enabled: !!geo.home_config_enabled,
          notif_batching_enabled: !!geo.notif_batching_enabled,
          beacon_first_mode: !!geo.beacon_first_mode,
          dup_window_minutes: Number(geo.dup_window_minutes) || 30,
          dup_same_zone: !!geo.dup_same_zone,
          dup_same_category: !!geo.dup_same_category,
        }),
      });
      setGeo(res);
      setFlagsMsg(`✓ ${t("saved")}`);
    } catch (e: any) {
      setFlagsMsg(e.message);
    }
  };

  const saveGeo = async () => {
    setGeoMsg("");
    try {
      const res = await api("/admin/settings", {
        method: "PATCH",
        body: JSON.stringify({ factory_lat: Number(geo.factory_lat), factory_lng: Number(geo.factory_lng), radius_meters: Number(geo.radius_meters), beacon_first_mode: !!geo.beacon_first_mode }),
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

  const addBeacon = async () => {
    setBMsg("");
    const en = bForm.en.trim();
    if (!en) {
      setBMsg(t("zoneEn"));
      return;
    }
    const payload: any = {
      zone_label_en: en,
      zone_label_hi: bForm.hi.trim() || en,
      zone_label_mr: bForm.mr.trim() || en,
    };
    if (bMode === "mac") {
      const mac = bForm.mac.trim().toUpperCase();
      if (!MAC_RE.test(mac)) {
        setBMsg(t("invalidMac"));
        return;
      }
      payload.mac_address = mac;
    } else {
      const uuid = bForm.uuid.trim().toLowerCase();
      if (!UUID_RE.test(uuid)) {
        setBMsg(t("invalidUuid"));
        return;
      }
      const major = Number(bForm.major);
      const minor = Number(bForm.minor);
      if (!Number.isInteger(major) || major < 0 || major > 65535 || !Number.isInteger(minor) || minor < 0 || minor > 65535) {
        setBMsg(t("invalidMajorMinor"));
        return;
      }
      payload.beacon_uuid = uuid;
      payload.major = major;
      payload.minor = minor;
    }
    try {
      await api("/admin/beacons", { method: "POST", body: JSON.stringify(payload) });
      setBForm({ mac: "", uuid: "", major: "", minor: "", en: "", hi: "", mr: "" });
      setBMsg(`✓ ${t("saved")}`);
      loadBeacons();
    } catch (e: any) {
      setBMsg(e.message);
    }
  };

  const bulkImport = async () => {
    setBulkMsg("");
    const uuid = bulk.uuid.trim().toLowerCase();
    if (!UUID_RE.test(uuid)) {
      setBulkMsg(t("invalidUuid"));
      return;
    }
    const major = Number(bulk.major);
    if (!Number.isInteger(major) || major < 0 || major > 65535) {
      setBulkMsg(t("invalidMajorMinor"));
      return;
    }
    // parse CSV lines: "minor,zone_name" (header optional)
    const rows: { minor: number; zone_name: string }[] = [];
    for (const raw of bulk.csv.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line) continue;
      const [m, ...rest] = line.split(",");
      const minor = Number(m.trim());
      const zone = rest.join(",").trim();
      if (!Number.isInteger(minor) || !zone || m.trim().toLowerCase() === "minor") continue;
      rows.push({ minor, zone_name: zone });
    }
    if (rows.length === 0) {
      setBulkMsg(t("bulkNoRows"));
      return;
    }
    try {
      const res = await api("/admin/beacons/bulk", {
        method: "POST",
        body: JSON.stringify({ beacon_uuid: uuid, major, department_code: bulk.dept.trim() || null, rows }),
      });
      setBulkMsg(`✓ ${t("bulkResult").replace("{a}", res.added).replace("{s}", res.skipped)}`);
      setBulk({ ...bulk, csv: "" });
      loadBeacons();
    } catch (e: any) {
      setBulkMsg(e.message);
    }
  };

  const toggleBeacon = async (b: any) => {
    try {
      await api(`/admin/beacons/${b.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !b.is_active }) });
      loadBeacons();
    } catch (e: any) {
      setBMsg(e.message);
    }
  };

  const deleteBeacon = async (b: any) => {
    try {
      await api(`/admin/beacons/${b.id}`, { method: "DELETE" });
      loadBeacons();
    } catch (e: any) {
      setBMsg(e.message);
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
            <h2>📱 {t("appver_title")}</h2>
            {!ver ? <Empty /> : (
              <div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
                  <div><label style={{ fontSize: 13, color: "var(--muted)" }}>{t("appver_latest")}</label><br />
                    <input data-testid="appver-version" style={{ width: 110, fontFamily: "monospace" }} placeholder="1.0.22"
                      value={ver.latest_version} onChange={(e) => setVer({ ...ver, latest_version: e.target.value })} /></div>
                  <div style={{ flex: 1, minWidth: 240 }}><label style={{ fontSize: 13, color: "var(--muted)" }}>{t("appver_url")}</label><br />
                    <input data-testid="appver-url" style={{ width: "100%" }} placeholder="https://play.google.com/store/apps/details?id=com.hogoplus.fs"
                      value={ver.apk_url} onChange={(e) => setVer({ ...ver, apk_url: e.target.value })} /></div>
                </div>
                <div style={{ marginTop: 8 }}>
                  <label style={{ fontSize: 13, color: "var(--muted)" }}>{t("appver_notes")}</label><br />
                  <input data-testid="appver-notes" style={{ width: "100%" }}
                    value={ver.notes} onChange={(e) => setVer({ ...ver, notes: e.target.value })} />
                </div>
                <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                    <input data-testid="appver-force" type="checkbox" checked={!!ver.force_update}
                      onChange={(e) => setVer({ ...ver, force_update: e.target.checked })} />
                    {t("appver_force")}
                  </label>
                  <button className="btn primary" data-testid="appver-save" onClick={saveVer}>{t("save")}</button>
                  {verMsg && <span style={{ fontSize: 13, color: verMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }} data-testid="appver-msg">{verMsg}</span>}
                </div>
                {!!ver.force_update && (
                  <p style={{ fontSize: 13, color: "var(--danger)", marginBottom: 0 }}>⚠️ {t("appver_force_warn")}</p>
                )}
              </div>
            )}
          </div>

          <div className="card">
            <h2>🚩 {t("flags_title")}</h2>
            {!geo ? <Empty /> : (
              <div>
                {([
                  ["vehicle_log_enabled", "flag_vehicle", "flag-vehicle-log"],
                  ["home_config_enabled", "flag_homecfg", "flag-home-config"],
                  ["notif_batching_enabled", "flag_notif", "flag-notif-batching"],
                  ["beacon_first_mode", "flag_beacon_first", "flag-beacon-first"],
                ] as [string, string, string][]).map(([key, label, tid]) => (
                  <label key={key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, padding: "4px 0" }}>
                    <input data-testid={tid} type="checkbox" checked={!!geo[key]}
                      onChange={(e) => setGeo({ ...geo, [key]: e.target.checked })} />
                    <span style={{
                      fontWeight: 700, fontSize: 11, padding: "1px 8px", borderRadius: 10,
                      background: geo[key] ? "var(--success, #1E8E4E)" : "var(--muted, #888)", color: "#fff",
                    }}>{geo[key] ? "ON" : "OFF"}</span>
                    {t(label)}
                  </label>
                ))}
                <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginTop: 6, paddingTop: 8, borderTop: "1px solid var(--border, #eee)" }}>
                  <span style={{ fontSize: 13, color: "var(--muted)" }}>{t("dup_rules")}:</span>
                  <label style={{ fontSize: 13 }}>
                    <input data-testid="dup-window" type="number" min={5} max={240} style={{ width: 60 }}
                      value={geo.dup_window_minutes ?? 30}
                      onChange={(e) => setGeo({ ...geo, dup_window_minutes: e.target.value })} /> {t("dup_minutes")}
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}>
                    <input data-testid="dup-zone" type="checkbox" checked={!!geo.dup_same_zone}
                      onChange={(e) => setGeo({ ...geo, dup_same_zone: e.target.checked })} />{t("dup_zone")}
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}>
                    <input data-testid="dup-category" type="checkbox" checked={!!geo.dup_same_category}
                      onChange={(e) => setGeo({ ...geo, dup_same_category: e.target.checked })} />{t("dup_category")}
                  </label>
                </div>
                <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 10 }}>
                  <button className="btn primary" data-testid="flags-save" onClick={saveFlags}>{t("save")}</button>
                  {flagsMsg && <span style={{ fontSize: 13, color: flagsMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>{flagsMsg}</span>}
                </div>
                <p style={{ fontSize: 12, color: "var(--muted)", marginBottom: 0 }}>{t("flags_hint")}</p>
              </div>
            )}
          </div>

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
                <div style={{ display: "flex", alignItems: "center", gap: 6, paddingBottom: 8 }}>
                  <input data-testid="geo-beacon-first" type="checkbox" checked={!!geo.beacon_first_mode}
                    onChange={(e) => setGeo({ ...geo, beacon_first_mode: e.target.checked })} />
                  <label style={{ fontSize: 13 }}>{t("beaconFirst")}</label>
                </div>
                <button className="btn primary" data-testid="geo-save" onClick={saveGeo}>{t("save")}</button>
                {geoMsg && <span style={{ fontSize: 13, color: geoMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>{geoMsg}</span>}
              </div>
            )}
          </div>

          <div className="card">
            <h2>📡 {t("beacons")} ({beacons.length})</h2>
            <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
              <button className={`btn ${bMode === "mac" ? "primary" : "ghost"}`} data-testid="beacon-mode-mac"
                style={{ padding: "6px 12px" }} onClick={() => { setBMode("mac"); setBMsg(""); }}>{t("modeMac")}</button>
              <button className={`btn ${bMode === "ibeacon" ? "primary" : "ghost"}`} data-testid="beacon-mode-ibeacon"
                style={{ padding: "6px 12px" }} onClick={() => { setBMode("ibeacon"); setBMsg(""); }}>{t("modeIbeacon")}</button>
            </div>
            {bMode === "mac" ? (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                <input data-testid="beacon-mac-input" style={{ width: 200, fontFamily: "monospace" }} placeholder="AA:BB:CC:DD:EE:FF"
                  value={bForm.mac} onChange={(e) => setBForm({ ...bForm, mac: e.target.value })} />
              </div>
            ) : (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                <input data-testid="beacon-uuid-input" style={{ flex: 1, minWidth: 280, fontFamily: "monospace" }}
                  placeholder="f7826da6-4fa2-4e98-8024-bc5b71e0893e"
                  value={bForm.uuid} onChange={(e) => setBForm({ ...bForm, uuid: e.target.value })} />
                <input data-testid="beacon-major-input" style={{ width: 90 }} type="number" placeholder={t("major")}
                  value={bForm.major} onChange={(e) => setBForm({ ...bForm, major: e.target.value })} />
                <input data-testid="beacon-minor-input" style={{ width: 90 }} type="number" placeholder={t("minor")}
                  value={bForm.minor} onChange={(e) => setBForm({ ...bForm, minor: e.target.value })} />
              </div>
            )}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
              <input data-testid="beacon-zone-en" style={{ flex: 1, minWidth: 120 }} placeholder={t("zoneEn")}
                value={bForm.en} onChange={(e) => setBForm({ ...bForm, en: e.target.value })} />
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <input style={{ flex: 1, minWidth: 120 }} placeholder={t("zoneHi")}
                value={bForm.hi} onChange={(e) => setBForm({ ...bForm, hi: e.target.value })} />
              <input style={{ flex: 1, minWidth: 120 }} placeholder={t("zoneMr")}
                value={bForm.mr} onChange={(e) => setBForm({ ...bForm, mr: e.target.value })} />
              <button className="btn primary" data-testid="beacon-add" onClick={addBeacon}>+ {t("addBeacon")}</button>
            </div>
            {bMsg && <div style={{ fontSize: 13, marginBottom: 8, color: bMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>{bMsg}</div>}

            <div style={{ borderTop: "1px solid var(--border)", margin: "10px 0", paddingTop: 10 }}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 6 }}>⬆️ {t("bulkImport")}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{t("bulkHint")}</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                <input data-testid="bulk-uuid" style={{ flex: 1, minWidth: 260, fontFamily: "monospace" }} placeholder={`UUID · ${t("major")}`}
                  value={bulk.uuid} onChange={(e) => setBulk({ ...bulk, uuid: e.target.value })} />
                <input data-testid="bulk-major" style={{ width: 90 }} type="number" placeholder={t("major")}
                  value={bulk.major} onChange={(e) => setBulk({ ...bulk, major: e.target.value })} />
                <input data-testid="bulk-dept" style={{ width: 130 }} placeholder={t("deptOptional")}
                  value={bulk.dept} onChange={(e) => setBulk({ ...bulk, dept: e.target.value })} />
              </div>
              <textarea data-testid="bulk-csv" style={{ width: "100%", minHeight: 90, fontFamily: "monospace", fontSize: 13 }}
                placeholder={"minor,zone_name\n1,Mill Gate\n2,Boiler House\n3,Pump Room"}
                value={bulk.csv} onChange={(e) => setBulk({ ...bulk, csv: e.target.value })} />
              <div style={{ marginTop: 6 }}>
                <button className="btn primary" data-testid="bulk-import" onClick={bulkImport}>{t("bulkImportBtn")}</button>
                {bulkMsg && <span style={{ marginLeft: 10, fontSize: 13, color: bulkMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>{bulkMsg}</span>}
              </div>
            </div>

            {beacons.length === 0 ? <Empty /> : beacons.map((b) => (
              <div key={b.id} className="feed-item" style={{ cursor: "default" }} data-testid={`beacon-row-${b.mac_address || b.id}`}>
                <div style={{ flex: 1 }}>
                  <div className="t">{b.zone_label_en} <Chip tone={b.mode === "ibeacon" ? "blue" : "amber"}>{b.mode === "ibeacon" ? t("modeIbeacon") : t("modeMac")}</Chip></div>
                  <div className="m" style={{ fontFamily: "monospace" }}>
                    {b.mode === "ibeacon" ? `${b.beacon_uuid} · M${b.major}/m${b.minor}` : (b.mac_address || "—")}
                    {b.department_code ? ` · ${b.department_code}` : ""}
                  </div>
                </div>
                <button className="btn ghost" style={{ padding: "6px 10px" }} onClick={() => toggleBeacon(b)}>
                  <Chip tone={b.is_active ? "green" : "red"}>{b.is_active ? t("active") : t("inactive")}</Chip>
                </button>
                <button className="btn danger" style={{ padding: "6px 10px" }} onClick={() => deleteBeacon(b)}>✕</button>
              </div>
            ))}
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
