import React, { useEffect, useState } from "react";
import { api, getAccess } from "../api";
import { Loading } from "../components";
import { useI18n } from "../i18n";

interface VehicleRow {
  id: string;
  plate: string;
  vehicle_type: string;
  direction: "in" | "out";
  driver_name: string | null;
  purpose: string | null;
  gate_zone: string | null;
  anpr_used: boolean;
  paired_log_id: string | null;
  logged_at: string;
  hours_inside?: number;
}

const TYPE_EMOJI: Record<string, string> = {
  truck: "🚛", tractor: "🚜", tempo: "🛻", car: "🚗", bike: "🏍️",
  bus: "🚌", jcb: "🚧", bullock_cart: "🐂", other: "🚙",
};

function istTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function Vehicles() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"log" | "inside">("log");
  const [date, setDate] = useState(() =>
    new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }),
  );
  const [plate, setPlate] = useState("");
  const [gate, setGate] = useState("");
  const [rows, setRows] = useState<VehicleRow[] | null>(null);
  const [inside, setInside] = useState<VehicleRow[] | null>(null);
  const [summary, setSummary] = useState<{ today_in: number; today_out: number; currently_inside: number } | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/vehicles/summary").then(setSummary).catch((e) => setErr(e.message));
    api("/vehicles/inside").then(setInside).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    const qs = new URLSearchParams({ day: date });
    if (plate.trim()) qs.set("plate", plate.trim());
    if (gate.trim()) qs.set("gate", gate.trim());
    api(`/vehicles/logs?${qs}`).then(setRows).catch((e) => setErr(e.message));
  }, [date, plate, gate]);

  const downloadXlsx = async () => {
    const res = await fetch(`/api/vehicles/export.xlsx?date_from=${date}&date_to=${date}`, {
      headers: { Authorization: `Bearer ${getAccess()}` },
    });
    if (!res.ok) { setErr(`Export failed (${res.status})`); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vehicle_register_${date}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const data = tab === "log" ? rows : inside;

  return (
    <div data-testid="vehicles-screen">
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0 }}>🚚 {t("veh_title")}</h1>
        <div style={{ flex: 1 }} />
        {summary && (
          <div style={{ display: "flex", gap: 14, fontWeight: 700 }}>
            <span style={{ color: "var(--success, #1E8E4E)" }}>IN {summary.today_in}</span>
            <span>OUT {summary.today_out}</span>
            <span style={{ color: "var(--warning, #C77700)" }} data-testid="veh-inside-count">
              {t("veh_inside")}: {summary.currently_inside}
            </span>
          </div>
        )}
        <button className="btn primary" data-testid="veh-export" onClick={downloadXlsx}>
          ⬇︎ XLSX
        </button>
      </div>

      <div style={{ display: "flex", gap: 10, margin: "14px 0", flexWrap: "wrap" }}>
        <button
          className={`btn ${tab === "log" ? "primary" : "ghost"}`}
          data-testid="veh-tab-log"
          onClick={() => setTab("log")}
        >
          {t("veh_tab_log")}
        </button>
        <button
          className={`btn ${tab === "inside" ? "primary" : "ghost"}`}
          data-testid="veh-tab-inside"
          onClick={() => setTab("inside")}
        >
          {t("veh_tab_inside")} {inside ? `(${inside.length})` : ""}
        </button>
        {tab === "log" && (
          <>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="veh-date" />
            <input
              placeholder={t("veh_filter_plate")}
              value={plate}
              onChange={(e) => setPlate(e.target.value)}
              data-testid="veh-filter-plate"
              style={{ width: 160 }}
            />
            <input
              placeholder={t("veh_filter_gate")}
              value={gate}
              onChange={(e) => setGate(e.target.value)}
              data-testid="veh-filter-gate"
              style={{ width: 160 }}
            />
          </>
        )}
      </div>

      {err && <div style={{ color: "var(--danger)", marginBottom: 10 }}>{err}</div>}
      {!data ? (
        <Loading />
      ) : data.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>{t("veh_empty")}</p>
      ) : (
        <table className="table" data-testid="veh-table">
          <thead>
            <tr>
              <th>{t("veh_col_time")}</th>
              <th>{t("veh_col_plate")}</th>
              <th>{t("veh_col_type")}</th>
              <th>IN/OUT</th>
              <th>{t("veh_col_driver")}</th>
              <th>{t("veh_col_purpose")}</th>
              <th>{t("veh_col_gate")}</th>
              <th>{t("veh_col_status")}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((v) => (
              <tr key={v.id}>
                <td>{istTime(v.logged_at)}</td>
                <td style={{ fontWeight: 700, letterSpacing: 1 }}>
                  {v.plate} {v.anpr_used ? "📷" : ""}
                </td>
                <td>{TYPE_EMOJI[v.vehicle_type] ?? ""} {v.vehicle_type}</td>
                <td>
                  <span style={{
                    padding: "2px 10px", borderRadius: 12, color: "#fff", fontWeight: 700,
                    background: v.direction === "in" ? "#1E8E4E" : "#0F5A6B",
                  }}>
                    {v.direction.toUpperCase()}
                  </span>
                </td>
                <td>{v.driver_name ?? "—"}</td>
                <td>{v.purpose ?? "—"}</td>
                <td>{v.gate_zone ?? "—"}</td>
                <td>
                  {typeof v.hours_inside === "number"
                    ? `${v.hours_inside}h ${t("veh_inside").toLowerCase()}`
                    : v.paired_log_id
                      ? t("veh_paired")
                      : v.direction === "in"
                        ? t("veh_still_inside")
                        : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
