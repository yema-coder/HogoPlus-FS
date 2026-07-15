import React, { useEffect, useState } from "react";
import { api } from "../api";
import { AgeChip, Chip, Empty, Loading } from "../components";
import { useI18n } from "../i18n";

export default function Approvals() {
  const { t } = useI18n();
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/dashboard/approvals-aging").then(setData).catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="card" style={{ color: "var(--danger)" }}>{err}</div>;
  if (!data) return <Loading />;

  return (
    <div>
      <div className="topbar"><h1 data-testid="approvals-title">{t("nav_approvals")}</h1></div>

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
