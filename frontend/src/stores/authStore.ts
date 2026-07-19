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

/** Fix (Prompt 7 Part E): permsPrimed was never restored on cold start, and on
 * existing installs the primer could be marked "seen" while core permissions were
 * still undetermined. Restore the flag AND re-show the primer ONCE if camera or
 * location is still undetermined (native only). */
async function resolvePermsPrimed(): Promise<boolean> {
  const { Platform } = await import("react-native");
  if (Platform.OS === "web") return true;
  const primed = Boolean(await storage.getItem<boolean>("hogo.permsPrimed", false));
  if (!primed) return false;
  const reprimed = Boolean(await storage.getItem<boolean>("hogo.permsReprimed", false));
  if (reprimed) return true;
  try {
    const [{ Camera }, Location] = await Promise.all([
      import("expo-camera"),
      import("expo-location"),
    ]);
    const cam = await Camera.getCameraPermissionsAsync();
    const loc = await Location.getForegroundPermissionsAsync();
    if (cam.status === "undetermined" || loc.status === "undetermined") {
      await storage.setItem("hogo.permsReprimed", true);
      return false; // re-show the primer once for this install
    }
  } catch {
    // permission modules unavailable (e.g. web bundle) — keep primed
  }
  return true;
}

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
    const permsPrimed = await resolvePermsPrimed();
    set({ permsPrimed });
    const hasTokens = await hydrateTokens();
    if (!hasTokens) {
      set({ status: "unauthenticated", langPicked });
      return;
    }
    // cache-first: paint Home instantly from the stored profile, revalidate in background
    const cachedRaw = await storage.getItem<string>("hogo.profile", "");
    if (cachedRaw) {
      try {
        const profile = JSON.parse(cachedRaw) as EmployeeProfile;
        await applyProfileLanguage(profile);
        set({ status: "authenticated", profile, langPicked });
        void get().refreshProfile();
        return;
      } catch {
        // corrupt cache — fall through to the network path
      }
    }
    try {
      const profile = await getMe();
      await storage.setItem("hogo.profile", JSON.stringify(profile));
      await applyProfileLanguage(profile);
      set({ status: "authenticated", profile, langPicked });
    } catch {
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
