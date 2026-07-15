import { create } from "zustand";

import {
  clearTokens,
  hydrateTokens,
  setSessionExpiredHandler,
  setTokens,
} from "@/src/api/client";
import { getMe } from "@/src/api/endpoints";
import type { EmployeeProfile } from "@/src/api/types";
import i18n from "@/src/i18n";
import { storage } from "@/src/utils/storage";

export type AuthStatus = "loading" | "unauthenticated" | "authenticated";

interface AuthState {
  status: AuthStatus;
  profile: EmployeeProfile | null;
  registrationToken: string | null;
  pendingPhone: string | null;
  langPicked: boolean;
  permsPrimed: boolean;
  hydrate: () => Promise<void>;
  setSession: (
    tokens: { access_token: string; refresh_token: string },
    profile: EmployeeProfile,
  ) => Promise<void>;
  refreshProfile: () => Promise<EmployeeProfile | null>;
  setRegistration: (token: string | null, phone: string | null) => void;
  markLangPicked: () => Promise<void>;
  markPermsPrimed: () => Promise<void>;
  logout: () => Promise<void>;
}

async function applyProfileLanguage(profile: EmployeeProfile): Promise<void> {
  const local = await storage.getItem<string>("hogo.lang", "");
  const lang = local || profile.language_pref || "mr";
  if (i18n.language !== lang) await i18n.changeLanguage(lang);
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "loading",
  profile: null,
  registrationToken: null,
  pendingPhone: null,
  langPicked: false,
  permsPrimed: false,

  hydrate: async () => {
    setSessionExpiredHandler(() => {
      void get().logout();
    });
    const langPicked = Boolean(await storage.getItem<boolean>("hogo.langPicked", false));
    const lang = await storage.getItem<string>("hogo.lang", "");
    if (lang && i18n.language !== lang) await i18n.changeLanguage(lang);
    const hasTokens = await hydrateTokens();
    if (!hasTokens) {
      set({ status: "unauthenticated", langPicked });
      return;
    }
    try {
      const profile = await getMe();
      await applyProfileLanguage(profile);
      set({ status: "authenticated", profile, langPicked });
    } catch {
      // keep cached profile-less session only if token refresh worked inside api();
      // if we land here the session is unusable
      const cached = await storage.getItem<string>("hogo.profile", "");
      if (cached) {
        try {
          const profile = JSON.parse(cached) as EmployeeProfile;
          set({ status: "authenticated", profile, langPicked });
          return;
        } catch {
          // fallthrough
        }
      }
      await clearTokens();
      set({ status: "unauthenticated", langPicked });
    }
  },

  setSession: async (tokens, profile) => {
    await setTokens(tokens.access_token, tokens.refresh_token);
    await storage.setItem("hogo.profile", JSON.stringify(profile));
    await applyProfileLanguage(profile);
    set({ status: "authenticated", profile, registrationToken: null, pendingPhone: null });
  },

  refreshProfile: async () => {
    try {
      const profile = await getMe();
      await storage.setItem("hogo.profile", JSON.stringify(profile));
      set({ profile });
      return profile;
    } catch {
      return null;
    }
  },

  setRegistration: (token, phone) => set({ registrationToken: token, pendingPhone: phone }),

  markLangPicked: async () => {
    await storage.setItem("hogo.langPicked", true);
    set({ langPicked: true });
  },

  markPermsPrimed: async () => {
    await storage.setItem("hogo.permsPrimed", true);
    set({ permsPrimed: true });
  },

  logout: async () => {
    await clearTokens();
    await storage.removeItem("hogo.profile");
    set({ status: "unauthenticated", profile: null, registrationToken: null, pendingPhone: null });
  },
}));
