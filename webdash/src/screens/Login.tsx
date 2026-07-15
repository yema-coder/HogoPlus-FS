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

export default function Login() {
  const { t, lang } = useI18n();
  const { login } = useAuth();
  const [mode, setMode] = useState<"otp" | "password">("otp");
  const [phone, setPhone] = useState("+91");
  const [otp, setOtp] = useState("");
  const [stage, setStage] = useState<"phone" | "otp">("phone");
  const [empId, setEmpId] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<any>(null); // must_change_password flow
  const [newPwd, setNewPwd] = useState("");
  const [newPwd2, setNewPwd2] = useState("");
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
      login(res.employee, res.access_token, res.refresh_token);
    } catch (e: any) {
      setError(localizedError(e.message, lang));
    } finally {
      setBusy(false);
    }
  };

  const passwordLogin = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api("/auth/password-login", {
        method: "POST",
        body: JSON.stringify({ emp_id: empId.trim(), password }),
      });
      if (res.must_change_password) {
        setTokens(res.access_token, res.refresh_token);
        setPending(res);
        return;
      }
      login(res.employee, res.access_token, res.refresh_token);
    } catch (e: any) {
      setError(localizedError(e.message, lang));
    } finally {
      setBusy(false);
    }
  };

  const submitForcedChange = async () => {
    if (newPwd.length < 8 || newPwd !== newPwd2) return;
    setBusy(true);
    setError("");
    try {
      await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: password, new_password: newPwd }),
      });
      login(pending.employee, pending.access_token, pending.refresh_token);
    } catch (e: any) {
      setError(localizedError(e.message, lang));
    } finally {
      setBusy(false);
    }
  };

  // ---- forced change-password screen ----
  if (pending) {
    return (
      <div className="login-wrap">
        <div className="login-card" data-testid="forced-change-card">
          <img src={logo} alt="HogoPlus-FS" style={{ width: 110, display: "block", margin: "0 auto 4px" }} />
          <h1 style={{ textAlign: "center" }}>{t("mustChangePwd")}</h1>
          <p style={{ color: "var(--muted)", fontSize: 14 }}>{t("mustChangePwdMsg")}</p>
          <label style={{ fontWeight: 600 }}>{t("newPassword")}</label>
          <input
            data-testid="new-password"
            type="password"
            value={newPwd}
            onChange={(e) => setNewPwd(e.target.value)}
          />
          <label style={{ fontWeight: 600 }}>{t("confirmPassword")}</label>
          <input
            data-testid="new-password-confirm"
            type="password"
            value={newPwd2}
            onChange={(e) => setNewPwd2(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitForcedChange()}
          />
          {newPwd.length > 0 && newPwd.length < 8 && (
            <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("pwdTooShort")}</div>
          )}
          {newPwd2.length > 0 && newPwd !== newPwd2 && (
            <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("pwdMismatch")}</div>
          )}
          <button
            data-testid="submit-change-password"
            className="btn primary"
            disabled={busy || newPwd.length < 8 || newPwd !== newPwd2}
            onClick={submitForcedChange}
          >
            {t("changePassword")}
          </button>
          {error && <div style={{ color: "var(--danger)", fontWeight: 600, fontSize: 14 }}>{error}</div>}
        </div>
      </div>
    );
  }

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
            {t("passwordLoginTab")}
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
            <label style={{ fontWeight: 600 }}>{t("empId")}</label>
            <input
              data-testid="login-empid"
              value={empId}
              onChange={(e) => setEmpId(e.target.value.toUpperCase())}
              placeholder="MD001"
            />
            <label style={{ fontWeight: 600 }}>{t("password")}</label>
            <input
              data-testid="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && passwordLogin()}
            />
            <button
              data-testid="login-password-submit"
              className="btn primary"
              disabled={busy || empId.trim().length === 0 || password.length === 0}
              onClick={passwordLogin}
            >
              {t("loginBtn")}
            </button>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{t("pwdLoginHint")}</div>
          </>
        )}
        {error && <div data-testid="login-error" style={{ color: "var(--danger)", fontWeight: 600, fontSize: 14 }}>{error}</div>}
      </div>
    </div>
  );
}
