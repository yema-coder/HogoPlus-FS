import React, { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import logo from "../logo.png";

export default function Login() {
  const { t } = useI18n();
  const { login } = useAuth();
  const [phone, setPhone] = useState("+91");
  const [otp, setOtp] = useState("");
  const [stage, setStage] = useState<"phone" | "otp">("phone");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const sendOtp = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/auth/send-otp", { method: "POST", body: JSON.stringify({ phone }) });
      setStage("otp");
    } catch (e: any) {
      setError(e.message);
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
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <img src={logo} alt="HogoPlus-FS" style={{ width: 110, display: "block", margin: "0 auto 4px" }} />
        <h1 style={{ textAlign: "center" }}>HogoPlus-FS — {t("commandCenter")}</h1>
        {stage === "phone" ? (
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
        )}
        {error && <div style={{ color: "var(--danger)", fontWeight: 600, fontSize: 14 }}>{error}</div>}
      </div>
    </div>
  );
}
