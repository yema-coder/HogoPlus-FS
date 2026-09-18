import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Chip, Loading } from "../components";
import { useI18n } from "../i18n";
import { PresenceTabs, STATUS_TONE, zoneName, type Worker } from "../presence/shared";

/** v1.0.26 Phase 2 — one-shot muster roll-call: inside / outside / unknown
 * RIGHT NOW. Deliberately NOT auto-refreshing — a muster is a snapshot. */

interface MusterResp {
  enabled: boolean; generated_at: string; scope?: string;
  counts?: { on_shift: number; inside: number; outside: number; unknown: number };
  groups?: { inside: Worker[]; outside: Worker[]; unknown: Worker[] };
}

const COLS: [keyof NonNullable<MusterResp["groups"]>, string, string][] = [
  ["inside", "ok", "✅"], ["outside", "bad", "🚨"], ["unknown", "unk", "❓"],
];

export default function PresenceMuster() {
  const { t, lang } = useI18n();
  const [snap, setSnap] = useState<MusterResp | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const take = async () => {
    setBusy(true);
    try {
      setSnap(await api("/presence/muster"));
      setError("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { take(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  if (error && !snap) return <div className="card" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!snap) return <Loading />;

  return (
    <>
      <div className="topbar">
        <h1 data-testid="muster-title">📋 {t("prs2_muster_title")}</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600 }} data-testid="muster-taken-at">
            {t("prs2_taken_at")}{" "}
            {new Date(snap.generated_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Asia/Kolkata" })}
          </span>
          <button className="btn primary" disabled={busy} onClick={take} data-testid="muster-retake">
            ↻ {t("prs2_retake")}
          </button>
          <button className="btn ghost" onClick={() => window.print()} data-testid="muster-print">
            🖨 {t("prs2_print")}
          </button>
        </div>
      </div>
      <PresenceTabs active="muster" />

      {!snap.enabled ? (
        <div className="card" style={{ textAlign: "center", padding: 40 }}>
          <h2>{t("prs_disabled_title")}</h2>
        </div>
      ) : (
        <>
          <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600, marginBottom: 12 }}>
            {t("prs2_muster_note")}
          </div>
          <div className="muster-cols" data-testid="muster-cols">
            {COLS.map(([key, cls, emoji]) => {
              const list = snap.groups?.[key] ?? [];
              return (
                <div key={key} className={`muster-col ${cls}`} data-testid={`muster-col-${key}`}>
                  <h3>{emoji} {t(`prs2_muster_${key}`)}</h3>
                  <div className="cnt" data-testid={`muster-count-${key}`}>{snap.counts?.[key] ?? 0}</div>
                  <div style={{ marginTop: 10 }}>
                    {list.map((w) => (
                      <div key={w.id} className="muster-person" data-testid={`muster-person-${w.emp_id}`}>
                        <span>
                          <Link to={`/presence/worker/${w.id}`} style={{ color: "inherit" }}>
                            <b>{w.full_name}</b>
                          </Link>{" "}
                          <span style={{ color: "var(--muted)", fontSize: 12 }}>{w.emp_id}</span>
                        </span>
                        <Chip tone={STATUS_TONE[w.status]}>
                          {w.zone_en ? zoneName(w, lang) : t(`prs_${w.status}`)}
                        </Chip>
                      </div>
                    ))}
                    {list.length === 0 && <div style={{ color: "var(--muted)", padding: 8 }}>{t("noData")}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
