import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Chip, Loading } from "../components";
import { useI18n } from "../i18n";

/** Vehicles quick view: search a plate (partial, case-insensitive) across
 * incidents + form submissions. Backend scopes results by role. */
export default function Vehicles() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const search = async () => {
    if (q.trim().length < 2) return;
    setBusy(true);
    setErr("");
    try {
      const res = await api(`/dashboard/plates/search?q=${encodeURIComponent(q.trim())}`);
      setResults(res.results);
    } catch (e: any) {
      setErr(e.message);
      setResults(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="topbar">
        <h1 data-testid="vehicles-title">🚗 {t("nav_vehicles")}</h1>
      </div>
      <div className="card">
        <div style={{ display: "flex", gap: 8 }}>
          <input
            data-testid="plate-search-input"
            value={q}
            onChange={(e) => setQ(e.target.value.toUpperCase())}
            placeholder={t("plateSearchHint")}
            onKeyDown={(e) => e.key === "Enter" && search()}
            style={{ flex: 1 }}
          />
          <button
            data-testid="plate-search-btn"
            className="btn primary"
            disabled={busy || q.trim().length < 2}
            onClick={search}
          >
            {t("searchBtn")}
          </button>
        </div>
        {err && <div style={{ color: "var(--danger)", marginTop: 8 }}>{err}</div>}
      </div>

      {busy && <Loading />}
      {results !== null && !busy && (
        <div className="card" data-testid="plate-results">
          <h2>{t("results")} ({results.length})</h2>
          {results.length === 0 && <div style={{ color: "var(--muted)" }}>{t("noPlateResults")}</div>}
          {results.map((r) => (
            <div
              key={`${r.type}-${r.id}`}
              className="feed-item"
              onClick={() => r.department_code && nav(`/dept/${r.department_code}`)}
            >
              <div style={{ width: 52, height: 52, borderRadius: 8, background: "var(--bg)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>
                {r.type === "incident" ? "⚠️" : "📋"}
              </div>
              <div style={{ flex: 1 }}>
                <div className="t">
                  <b style={{ color: "var(--primary, #1a6b3c)" }}>🚗 {r.plate}</b> · {r.label}
                </div>
                <div className="m">
                  {r.type === "incident" ? t("t_incident") : t("t_submission")} · {r.department_code || "—"} ·{" "}
                  {r.created_at ? new Date(r.created_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : ""}
                </div>
              </div>
              <Chip>{r.status}</Chip>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
