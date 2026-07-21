import { useRouter } from "expo-router";
import { useEffect, useRef } from "react";
import { AppState, Platform } from "react-native";

import { patchMe } from "@/src/api/endpoints";
import { useAuthStore } from "@/src/stores/authStore";
import { storage } from "@/src/utils/storage";

import {
  addNotificationTapListener,
  configureForegroundNotificationsSafe,
  registerPushTokenSafe,
} from "./safeNotifications";

/**
 * Prompt 17 Part E: once authenticated, register the Expo push token with the
 * backend (built APKs only — safe no-op in Expo Go / web) and deep-link pushes.
 * Also refreshes the profile on every app foreground so role changes made by
 * Time Office / CGM propagate WITHOUT re-login (Part B).
 */
export function usePushSetup(): void {
  const status = useAuthStore((s) => s.status);
  const refreshProfile = useAuthStore((s) => s.refreshProfile);
  const router = useRouter();
  const registered = useRef(false);

  useEffect(() => {
    if (status !== "authenticated" || registered.current || Platform.OS === "web") return;
    registered.current = true;
    configureForegroundNotificationsSafe();
    void (async () => {
      const token = await registerPushTokenSafe();
      if (!token) return;
      const last = await storage.getItem<string>("hogo.pushToken", "");
      if (last === token) return;
      try {
        await patchMe({ expo_push_token: token });
        await storage.setItem("hogo.pushToken", token);
      } catch {
        // retried on next launch
      }
    })();
  }, [status]);

  useEffect(() => {
    return addNotificationTapListener((data) => {
      const type = String(data?.entity_type ?? "");
      const id = data?.entity_id ? String(data.entity_id) : "";
      if (type === "incident" && id) router.push(`/incident/${id}`);
      else router.push("/(tabs)/alerts");
    });
  }, [router]);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active" && useAuthStore.getState().status === "authenticated") {
        void refreshProfile();
      }
    });
    return () => sub.remove();
  }, [refreshProfile]);
}
