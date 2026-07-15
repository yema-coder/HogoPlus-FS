import React, { useEffect, useRef, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { isTopMgmt, useAuth } from "../auth";
import { Chip, Empty } from "../components";
import { useI18n } from "../i18n";

interface Msg { role: "user" | "assistant"; content: string; citations?: { doc_title: string; page: number }[] }

export default function Reports() {
  const { t } = useI18n();
  const { user } = useAuth();
  const top = isTopMgmt(user);
  const [reports, setReports] = useState<any[] | null>(null);
  const [usage, setUsage] = useState<any>(null);
  const [genBusy, setGenBusy] = useState(false);
  const [genMsg, setGenMsg] = useState("");

  // chat
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const convId = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (top) {
      api("/dashboard/reports").then((r) => setReports(r.reports)).catch(() => setReports([]));
      api("/admin/ai-usage").then(setUsage).catch(() => {});
    }
  }, [top]);

  const generate = async () => {
    setGenBusy(true);
    setGenMsg("");
    try {
      await api("/admin/generate-report", { method: "POST", body: JSON.stringify({}) });
      setGenMsg(`✓ ${t("generated")}`);
      const r = await api("/dashboard/reports");
      setReports(r.reports);
    } catch (e: any) {
      setGenMsg(e.message);
    } finally {
      setGenBusy(false);
    }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || chatBusy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setChatBusy(true);
    try {
      const res = await api("/ai/chat", {
        method: "POST",
        body: JSON.stringify({ message: text, conversation_id: convId.current }),
      });
      convId.current = res.conversation_id;
      setMsgs((m) => [...m, { role: "assistant", content: res.answer, citations: res.citations }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", content: `⚠ ${e.message}` }]);
    } finally {
      setChatBusy(false);
      setTimeout(() => scroller.current?.scrollTo({ top: 99999, behavior: "smooth" }), 50);
    }
  };

  return (
    <div>
      <div className="topbar"><h1 data-testid="reports-title">{t("nav_reports")}</h1></div>
      <div className="grid">
        <div>
          {top && (
            <div className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h2 style={{ margin: 0 }}>{t("dailyReports")}</h2>
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  {genMsg && <span style={{ fontSize: 13, color: "var(--muted)" }}>{genMsg}</span>}
                  <button className="btn primary" data-testid="generate-report" disabled={genBusy} onClick={generate}>
                    {genBusy ? t("loading") : t("generate")}
                  </button>
                </div>
              </div>
              {reports === null ? <div style={{ color: "var(--muted)" }}>{t("loading")}</div> : reports.length === 0 ? <div style={{ color: "var(--muted)" }}>{t("noReports")}</div> : (
                <table data-testid="reports-table">
                  <thead><tr><th>{t("date")}</th><th>Lang</th><th></th></tr></thead>
                  <tbody>
                    {reports.map((r) => (
                      <tr key={r.key}>
                        <td>{r.date}</td>
                        <td><Chip tone="blue">{r.lang.toUpperCase()}</Chip></td>
                        <td><a href={r.url} target="_blank" rel="noreferrer" className="btn ghost" style={{ padding: "6px 12px" }}>⬇ {t("download")}</a></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {top && usage && (
            <div className="card">
              <h2>{t("aiUsage")}</h2>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={usage.history}>
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="total" stroke="#3A5DAE" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                {Object.entries(usage.counts || {}).map(([k, v]) => (
                  <Chip key={k} tone="blue">{k}: {v as number}</Chip>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <h2>🤖 {t("chatTitle")}</h2>
          <div className="chat">
            <div className="msgs" ref={scroller} data-testid="chat-messages">
              {msgs.length === 0 && <Empty />}
              {msgs.map((m, i) => (
                <div key={i} className={`bubble ${m.role === "user" ? "user" : "bot"}`}>
                  {m.content}
                  {m.citations && m.citations.length > 0 && (
                    <div style={{ marginTop: 6, fontSize: 12, color: "var(--muted)" }}>
                      {t("sources")}: {m.citations.map((c) => `${c.doc_title} (${t("page")} ${c.page})`).join(", ")}
                    </div>
                  )}
                </div>
              ))}
              {chatBusy && <div className="bubble bot">…</div>}
            </div>
            <div className="bar">
              <input
                data-testid="chat-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={t("chatPh")}
                onKeyDown={(e) => e.key === "Enter" && send()}
              />
              <button className="btn primary" data-testid="chat-send" disabled={chatBusy || !input.trim()} onClick={send}>{t("send")}</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
