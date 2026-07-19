import React, { useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider, canUseDashboard, isTopMgmt, useAuth } from "./auth";
import { LangSwitcher, Loading } from "./components";
import eyeBase from "./eye-base.png";
import { LangProvider, useI18n } from "./i18n";
import Admin from "./screens/Admin";
import Approvals from "./screens/Approvals";
import Attendance from "./screens/Attendance";
import Department from "./screens/Department";
import Login from "./screens/Login";
import Overview from "./screens/Overview";
import Reports from "./screens/Reports";
import Vehicles from "./screens/Vehicles";
import logo from "./logo.png";
import { api } from "./api";

function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async () => {
    setBusy(true);
    setMsg("");
    try {
      await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setMsg(t("pwdChanged"));
      setTimeout(onClose, 1200);
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap" style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.5)" }} onClick={onClose}>
      <div className="login-card" data-testid="change-password-modal" onClick={(e) => e.stopPropagation()}>
        <h1>{t("changePassword")}</h1>
        <label style={{ fontWeight: 600 }}>{t("currentPassword")}</label>
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <label style={{ fontWeight: 600 }}>{t("newPassword")}</label>
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        {next.length > 0 && next.length < 8 && <div style={{ color: "var(--danger)", fontSize: 13 }}>{t("pwdTooShort")}</div>}
        <button className="btn primary" disabled={busy || current.length === 0 || next.length < 8} onClick={submit}>
          {t("changePassword")}
        </button>
        <button className="btn ghost" onClick={onClose}>{t("back")}</button>
        {msg && <div style={{ fontWeight: 600, fontSize: 14 }}>{msg}</div>}
      </div>
    </div>
  );
}

function Layout() {
  const { user, booting, logout } = useAuth();
  const { t, lang } = useI18n();
  const [pwdModal, setPwdModal] = useState(false);
  if (booting) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (!canUseDashboard(user)) {
    return (
      <div className="login-wrap">
        <div className="login-card" style={{ textAlign: "center" }}>
          <h1>{t("accessDenied")}</h1>
          <p style={{ color: "var(--muted)" }}>{t("accessDeniedMsg")}</p>
          <button className="btn primary" onClick={logout}>{t("logout")}</button>
        </div>
      </div>
    );
  }
  const roleLabel = user.role ? (user.role as any)[`label_${lang}`] || user.role.label_en : "";
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <img src={logo} alt="HogoPlus-FS" style={{ width: 40, height: 33 }} />
          <div>
            HogoPlus-FS
            <div style={{ fontSize: 12, opacity: 0.7 }}>{t("commandCenter")}</div>
          </div>
        </div>
        <NavLink to="/" end>{t("nav_overview")}</NavLink>
        <NavLink to="/approvals">{t("nav_approvals")}</NavLink>
        <NavLink to="/attendance">{t("nav_attendance")}</NavLink>
        <NavLink to="/reports">{t("nav_reports")}</NavLink>
        <NavLink to="/vehicles">🚗 {t("nav_vehicles")}</NavLink>
        {isTopMgmt(user) && <NavLink to="/admin">{t("nav_admin")}</NavLink>}
        <div style={{ flex: 1 }} />
        <div style={{ padding: "10px 12px", fontSize: 13, opacity: 0.85 }}>
          <b>{user.full_name}</b>
          <div style={{ opacity: 0.8 }}>{roleLabel}{user.department_code ? ` · ${user.department_code}` : ""}</div>
        </div>
        {isTopMgmt(user) && (
          <button
            data-testid="open-change-password"
            className="btn ghost"
            style={{ color: "#fff", borderColor: "rgba(255,255,255,0.3)", marginBottom: 8 }}
            onClick={() => setPwdModal(true)}
          >
            {t("changePassword")}
          </button>
        )}
        <button className="btn ghost" style={{ color: "#fff", borderColor: "rgba(255,255,255,0.3)" }} onClick={logout}>
          {t("logout")}
        </button>
      </nav>
      <main className="main">
        <Outlet />
      </main>
      <footer className="brand-footer" data-testid="brand-footer">
        <img src={eyeBase} alt="" />
        <span>HogoPlus-FS</span>
      </footer>
      {pwdModal && <ChangePasswordModal onClose={() => setPwdModal(false)} />}
    </div>
  );
}

function LoginGate() {
  const { user, booting } = useAuth();
  if (booting) return <Loading />;
  if (user) return <Navigate to="/" replace />;
  return <Login />;
}

export default function App() {
  return (
    <LangProvider>
      <AuthProvider>
        <BrowserRouter basename="/api/dash">
          <div style={{ position: "fixed", top: 14, right: 20, zIndex: 60 }}>
            <LangSwitcher />
          </div>
          <Routes>
            <Route path="/login" element={<LoginGate />} />
            <Route element={<Layout />}>
              <Route path="/" element={<Overview />} />
              <Route path="/dept/:code" element={<Department />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/attendance" element={<Attendance />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/vehicles" element={<Vehicles />} />
              <Route path="/admin" element={<Admin />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </LangProvider>
  );
}
