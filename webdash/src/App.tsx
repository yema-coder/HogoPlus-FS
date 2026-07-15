import React from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider, canUseDashboard, isTopMgmt, useAuth } from "./auth";
import { LangSwitcher, Loading } from "./components";
import { LangProvider, useI18n } from "./i18n";
import Admin from "./screens/Admin";
import Approvals from "./screens/Approvals";
import Attendance from "./screens/Attendance";
import Department from "./screens/Department";
import Login from "./screens/Login";
import Overview from "./screens/Overview";
import Reports from "./screens/Reports";

function Layout() {
  const { user, booting, logout } = useAuth();
  const { t, lang } = useI18n();
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
        <div className="brand">🏭 {t("brand")}<div style={{ fontSize: 12, opacity: 0.7 }}>{t("commandCenter")}</div></div>
        <NavLink to="/" end>{t("nav_overview")}</NavLink>
        <NavLink to="/approvals">{t("nav_approvals")}</NavLink>
        <NavLink to="/attendance">{t("nav_attendance")}</NavLink>
        <NavLink to="/reports">{t("nav_reports")}</NavLink>
        {isTopMgmt(user) && <NavLink to="/admin">{t("nav_admin")}</NavLink>}
        <div style={{ flex: 1 }} />
        <div style={{ padding: "10px 12px", fontSize: 13, opacity: 0.85 }}>
          <b>{user.full_name}</b>
          <div style={{ opacity: 0.8 }}>{roleLabel}{user.department_code ? ` · ${user.department_code}` : ""}</div>
        </div>
        <button className="btn ghost" style={{ color: "#fff", borderColor: "rgba(255,255,255,0.3)" }} onClick={logout}>
          {t("logout")}
        </button>
      </nav>
      <main className="main">
        <Outlet />
      </main>
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
              <Route path="/admin" element={<Admin />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </LangProvider>
  );
}
