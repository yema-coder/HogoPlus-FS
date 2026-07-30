import React, { useEffect, useState } from "react";
import { api } from "../api";
import { AgeChip, Chip, Empty, Loading } from "../components";
import { useI18n } from "../i18n";

export default function Approvals() {
  const { t } = useI18n();
  const [data, setData] = useState<any>(null);
  const [regs, setRegs] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/dashboard/approvals-aging").then(setData).catch((e) => setErr(e.message));
    api("/dashboard/pending-registrations").then(setRegs).catch(() => setRegs({ items: [] }));
  }, []);

  if (err) return <div className="card" style={{ color: "var(--danger)" }}>{err}</div>;
  if (!data) return <Loading />;

  const osmTile = (lat: number, lng: number, zoom = 16) => {
    const n = 2 ** zoom;
    const xF = ((lng + 180) / 360) * n;
    const latR = (lat * Math.PI) / 180;
    const yF = ((1 - Math.log(Math.tan(latR) + 1 / Math.cos(latR)) / Math.PI) / 2) * n;
    return {
      url: `https://tile.openstreetmap.org/${zoom}/${Math.floor(xF)}/${Math.floor(yF)}.png`,
      px: (xF - Math.floor(xF)) * 256,
      py: (yF - Math.floor(yF)) * 256,
    };
  };

  return (
    <div>
      <div className="topbar"><h1 data-testid="approvals-title">{t("nav_approvals")}</h1></div>

      {regs && regs.items.length > 0 ? (
        <div className="card" data-testid="pending-registrations-card">
          <h2>{t("pendingRegs")} ({regs.items.length})</h2>
          <div className="mgr-cards">
            {regs.items.map((r: any) => {
              const tile = r.reg_lat != null && r.reg_lng != null ? osmTile(r.reg_lat, r.reg_lng) : null;
              return (
                <div key={r.id} className="tile" style={{ cursor: "default" }} data-testid={`pending-reg-${r.id}`}>
                  <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                    {r.selfie_url ? (
                      <a href={r.selfie_url} target="_blank" rel="noreferrer">
                        <img src={r.selfie_url} alt="" style={{ width: 64, height: 64, borderRadius: 10, objectFit: "cover" }} />
                      </a>
                    ) : null}
                    <div style={{ minWidth: 0 }}>
                      <h3 style={{ margin: 0 }}>{r.full_name}</h3>
                      <div style={{ fontSize: 13, color: "var(--muted)" }}>{r.phone}</div>
                      <div style={{ fontSize: 13 }}>
                        {t("wantsDept")}: <b>{r.department_code || "—"}</b> · {r.role_code}
                      </div>
                      <div style={{ fontSize: 13 }}>{t("suggestedId")}: <b>{r.emp_id || r.suggested_emp_id}</b></div>
                    </div>
                  </div>
                  {r.created_at ? (
                    <div className="row"><span>{t("registered")}</span>
                      <b>{new Date(r.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</b>
                    </div>
                  ) : null}
                  <div className="row">
                    <span>📍</span>
                    {r.reg_lat != null ? (
                      <b style={{ color: r.reg_inside_geofence ? "var(--success, #2e7d32)" : "var(--danger)" }}>
                        {r.reg_inside_geofence ? `✓ ${t("insideFactory")}` : `✗ ${t("outsideFactory")}`}
                      </b>
                    ) : (
                      <b style={{ color: "var(--muted)" }}>{t("noLocation")}</b>
                    )}
                  </div>
                  {r.reg_address ? <div style={{ fontSize: 12, color: "var(--muted)" }}>{r.reg_address}</div> : null}
                  {r.reg_zone ? <div style={{ fontSize: 12 }}>📡 {r.reg_zone}</div> : null}
                  {tile ? (
                    <div style={{ position: "relative", height: 110, borderRadius: 8, overflow: "hidden", marginTop: 6 }}>
                      <img
                        src={tile.url}
                        alt=""
                        style={{ position: "absolute", width: 256, height: 256, left: `calc(50% - ${tile.px}px)`, top: 55 - tile.py }}
                      />
                      <span style={{ position: "absolute", left: "50%", top: 55, transform: "translate(-50%,-50%)", fontSize: 18 }}>📍</span>
                    </div>
                  ) : null}
                  <div className="row" style={{ marginTop: 6 }}>
                    <span>{r.reg_face_count != null && r.reg_face_count > 0 ? `✅ ${t("faceOk")}` : `⚠️ ${t("faceUnknown")}`}</span>
                    <b style={{ fontSize: 12, color: "var(--muted)" }}>
                      {r.reg_device || ""}{r.reg_app_version ? ` · v${r.reg_app_version}` : ""}
                    </b>
                  </div>
                  {(r.duplicate_hints || []).length > 0 ? (
                    <div style={{ marginTop: 6, padding: 8, borderRadius: 8, background: "rgba(217,64,89,.08)", border: "1px solid var(--danger)" }} data-testid={`reg-dup-${r.id}`}>
                      <b style={{ color: "var(--danger)", fontSize: 13 }}>⚠️ {t("possibleDuplicate")}</b>
                      {r.duplicate_hints.map((h: any) => (
                        <div key={h.emp_id} style={{ fontSize: 12 }}>{h.full_name} · {h.emp_id}{h.phone ? ` · ${h.phone}` : ""}</div>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="card">
        <h2>{t("byManager")}</h2>
        {data.summary.length === 0 ? <Empty /> : (
          <div className="mgr-cards" data-testid="approvals-summary">
            {data.summary.map((m: any, i: number) => (
              <div key={i} className={`tile ${m.oldest_hours > 24 ? "red" : m.oldest_hours > 8 ? "amber" : ""}`} style={{ cursor: "default" }}>
                <h3>{m.manager || `— (${m.department_code})`}</h3>
                <div className="row"><span>{t("pending")}</span><b>{m.pending}</b></div>
                <div className="row"><span>{t("oldest")}</span><b>{m.oldest_hours}</b></div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2>{t("pendingApprovals")} ({data.items.length})</h2>
        {data.items.length === 0 ? <Empty /> : (
          <table data-testid="approvals-table">
            <thead>
              <tr><th>{t("type")}</th><th>{t("department")}</th><th>{t("manager")}</th><th>{t("age")}</th><th>{t("escalated")}</th></tr>
            </thead>
            <tbody>
              {data.items.map((it: any) => (
                <tr key={`${it.type}-${it.id}`} className={it.age_hours > 24 ? "red" : it.age_hours > 8 ? "amber" : ""}>
                  <td><Chip tone="blue">{t(`t_${it.type}`)}</Chip></td>
                  <td>{it.department_code}</td>
                  <td>{it.manager || "—"}</td>
                  <td><AgeChip hours={it.age_hours} /></td>
                  <td>{it.escalated ? <Chip tone="red">⬆ {t("escalated")}</Chip> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
