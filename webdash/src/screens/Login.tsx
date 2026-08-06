import React, { useState } from "react";

import { api, setTokens } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import logo from "../logo.png";

/** Lockout & other backend errors may arrive as trilingual JSON dicts. */
function localizedError(raw: string, lang: string): string {
  try {
    const j = JSON.parse(raw);
    if (j && typeof j === "object" && j.en) return j[lang] || j.en;
  } catch {
    /* plain string */
  }
  return raw;
}

/** v1.0.24 MD ACCESS REDESIGN — two paths only:
 *  - Password tab: the shared MD password ALONE (no emp_id). /auth/md-login is
 *    rate-limited per-IP + globally and every attempt is audited.
 *  - OTP tab: normal OTP; afterwards /auth/md-elevate promotes the two
 *    whitelisted numbers to the MD dashboard (audited with the number used).
 *    Non-whitelisted dashboard roles (CGM/TO managers) continue as themselves. */
export default function Login() {
  const { t, lang } = useI18n();
  const { login } = useAuth();
  const [mode, setMode] = useState<"otp" | "password">("otp");
  const [phone, setPhone] = useState("+91");
  const [otp, setOtp] = useState("");
  const [stage, setStage] = useState<"phone" | "otp">("phone");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const sendOtp = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/auth/send-otp", { method: "POST", body: JSON.stringify({ phone }) });
      setStage("otp");
    } catch (e: any) {
      setError(localizedError(e.message, lang));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api("/auth/verify-otp", { method: "POST", body: JSON.stringify({ phone, otp }) });
      if (res.is_new) {
        setError(t("accessDeniedMsg"));
        return;
      }
      // MD elevation: whitelisted numbers land on the MD dashboard
      setTokens(res.access_token, res.refresh_token);
      try {
        const md = await api("/auth/md-elevate", { method: "POST" });
        login(md.employee, md.access_token, md.refresh_token);
        return;
      } catch {
        /* not MD-whitelisted — continue with the personal dashboard role */
      }
      login(res.employee, res.access_token, res.refresh_token);
    } catch (e: any) {
      setError(localizedError(e.message, lang));
    } finally {
      setBusy(false);
    }
  };

  const mdLogin = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api("/auth/md-login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      login(res.employee, res.access_token, res.refresh_token);
    } catch (e: any) {
      setError(localizedError(e.message, lang));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <img src={logo} alt="HogoPlus-FS" style={{ width: 110, display: "block", margin: "0 auto 4px" }} />
        <h1 style={{ textAlign: "center" }}>HogoPlus-FS — {t("commandCenter")}</h1>

        <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
          <button
            data-testid="tab-otp"
            className={`btn ${mode === "otp" ? "primary" : "ghost"}`}
            style={{ flex: 1 }}
            onClick={() => { setMode("otp"); setError(""); }}
          >
            {t("otpLoginTab")}
          </button>
          <button
            data-testid="tab-password"
            className={`btn ${mode === "password" ? "primary" : "ghost"}`}
            style={{ flex: 1 }}
            onClick={() => { setMode("password"); setError(""); }}
          >
            {t("mdLoginTab")}
          </button>
        </div>

        {mode === "otp" ? (
          stage === "phone" ? (
            <>
              <label style={{ fontWeight: 600 }}>{t("phone")}</label>
              <input
                data-testid="login-phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/[^+0-9]/g, ""))}
                placeholder="+91XXXXXXXXXX"
                onKeyDown={(e) => e.key === "Enter" && sendOtp()}
              />
              <button data-testid="login-send-otp" className="btn primary" disabled={busy || phone.length < 13} onClick={sendOtp}>
                {t("sendOtp")}
              </button>
            </>
          ) : (
            <>
              <div style={{ color: "var(--success)", fontWeight: 600 }}>✓ {t("otpSent")} — {phone}</div>
              <label style={{ fontWeight: 600 }}>{t("otp")}</label>
              <input
                data-testid="login-otp"
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && verify()}
              />
              <button data-testid="login-verify" className="btn primary" disabled={busy || otp.length !== 6} onClick={verify}>
                {t("verify")}
              </button>
              <button className="btn ghost" onClick={() => { setStage("phone"); setOtp(""); setError(""); }}>
                {t("changePhone")}
              </button>
            </>
          )
        ) : (
          <>
            <label style={{ fontWeight: 600 }}>{t("mdPassword")}</label>
            <input
              data-testid="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && mdLogin()}
            />
            <button
              data-testid="login-password-submit"
              className="btn primary"
              disabled={busy || password.length === 0}
              onClick={mdLogin}
            >
              {t("loginBtn")}
            </button>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{t("mdLoginHint")}</div>
          </>
        )}
        {error && <div data-testid="login-error" style={{ color: "var(--danger)", fontWeight: 600, fontSize: 14 }}>{error}</div>}
      </div>
    </div>
  );
}
