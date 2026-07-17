import React from "react";
import eyeBase from "./eye-base.png";
import eyeIris from "./eye-iris.png";
import { useI18n } from "./i18n";

export function Chip({ tone, children }: { tone?: "red" | "amber" | "green" | "blue"; children: React.ReactNode }) {
  return <span className={`chip ${tone || ""}`}>{children}</span>;
}

export function AgeChip({ hours }: { hours: number }) {
  const tone = hours > 24 ? "red" : hours > 8 ? "amber" : "green";
  return <Chip tone={tone}>{hours >= 48 ? `${Math.round(hours / 24)}d` : `${Math.round(hours)}h`}</Chip>;
}

export function Loading() {
  const { t } = useI18n();
  return (
    <div className="eye-loading" role="status" aria-label={t("loading")}>
      <div className="eye-loader">
        <img className="eye-base" src={eyeBase} alt="" />
        <img className="eye-iris" src={eyeIris} alt="" />
      </div>
      <div>{t("loading")}</div>
    </div>
  );
}

export function Empty() {
  const { t } = useI18n();
  return <div style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>{t("noData")}</div>;
}

export function KPI({ label, value, red, onClick }: { label: string; value: React.ReactNode; red?: boolean; onClick?: () => void }) {
  return (
    <div className="kpi" onClick={onClick}>
      <div className={`v ${red ? "red" : ""}`}>{value}</div>
      <div className="l">{label}</div>
    </div>
  );
}

export function LangSwitcher() {
  const { lang, setLang } = useI18n();
  return (
    <div className="tabs" style={{ margin: 0 }}>
      {(["en", "hi", "mr"] as const).map((l) => (
        <button key={l} className={lang === l ? "on" : ""} onClick={() => setLang(l)} style={{ padding: "4px 12px" }}>
          {l === "en" ? "EN" : l === "hi" ? "हिं" : "मरा"}
        </button>
      ))}
    </div>
  );
}

export const fmtTime = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }) : "—";

export function VerifChip({ level }: { level: string | null }) {
  if (level === "flagged") return <Chip tone="red">⚑ flagged</Chip>;
  if (level === "verified" || level === "full") return <Chip tone="green">✓ {level}</Chip>;
  return <Chip>{level || "—"}</Chip>;
}
