import React, { createContext, useContext, useEffect, useState } from "react";
import { api, clearTokens, getAccess, setTokens } from "./api";

export interface Profile {
  id: string;
  emp_id: string;
  full_name: string;
  phone: string;
  department_code: string | null;
  role_code: string;
  role: { code: string; rank: number; label_en: string; label_hi: string; label_mr: string } | null;
  language_pref: string;
}

interface AuthState {
  user: Profile | null;
  booting: boolean;
  login: (profile: Profile, access: string, refresh: string) => void;
  logout: () => void;
}

const Ctx = createContext<AuthState>({ user: null, booting: true, login: () => {}, logout: () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Profile | null>(null);
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    if (!getAccess()) {
      setBooting(false);
      return;
    }
    api("/auth/me")
      .then((p) => setUser(p))
      .catch(() => clearTokens())
      .finally(() => setBooting(false));
  }, []);

  const login = (profile: Profile, access: string, refresh: string) => {
    setTokens(access, refresh);
    setUser(profile);
  };
  const logout = () => {
    clearTokens();
    setUser(null);
  };

  return <Ctx.Provider value={{ user, booting, login, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);

/** rank helpers: 1=MD 2=CGM 3=Manager */
export const rankOf = (u: Profile | null) => u?.role?.rank ?? 99;
export const isTopMgmt = (u: Profile | null) => rankOf(u) <= 2; // MD / CGM
export const canUseDashboard = (u: Profile | null) => rankOf(u) <= 3;
export const canReviewAttendance = (u: Profile | null) =>
  isTopMgmt(u) || (rankOf(u) === 3 && u?.department_code === "TIME_OFFICE");
