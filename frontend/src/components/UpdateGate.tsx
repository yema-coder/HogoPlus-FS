/**
 * v1.0.17 — Google Play In-App Updates gate (item 4).
 * On app open (and each foreground return) checks the backend's app-version row;
 * when a newer version exists, runs the native Play in-app update flow:
 *   - FLEXIBLE by default (background download, auto-install when done)
 *   - IMMEDIATE (blocking full-screen) when the backend row has force_update=true
 * Fails OPEN everywhere Play isn't available (sideloaded APK, Expo Go, web, iOS):
 * any error is swallowed and the existing backend-driven <UpdateBanner /> remains
 * the fallback prompt — the app never crashes on non-Play installs.
 */
import Constants from "expo-constants";
import { useEffect, useRef } from "react";
import { AppState, Platform } from "react-native";

import { getAppVersion } from "@/src/api/endpoints";

function isNewer(latest: string, current: string): boolean {
  const a = latest.split(".").map((n) => parseInt(n, 10) || 0);
  const b = current.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) > (b[i] ?? 0)) return true;
    if ((a[i] ?? 0) < (b[i] ?? 0)) return false;
  }
  return false;
}

export function UpdateGate() {
  const busy = useRef(false);

  useEffect(() => {
    // Native Play flow: Android production/dev builds only
    if (Platform.OS !== "android" || Constants.appOwnership === "expo") return;

    const run = async () => {
      if (busy.current) return;
      busy.current = true;
      try {
        const current = Constants.expoConfig?.version ?? "0.0.0";
        const info = await getAppVersion();
        if (!info.latest_version || !isNewer(info.latest_version, current)) return;
        // lazy require: keeps Expo Go/web bundles from touching the native module
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const mod = require("sp-react-native-in-app-updates");
        const SpInAppUpdates = mod.default ?? mod;
        const updater = new SpInAppUpdates(false);
        const check = await updater.checkNeedsUpdate({ curVersion: current });
        if (!check?.shouldUpdate) return; // sideloaded / not a Play install → UpdateBanner covers it
        if (info.force_update) {
          await updater.startUpdate({ updateType: mod.IAUUpdateKind.IMMEDIATE });
        } else {
          // flexible: install as soon as the background download completes
          updater.addStatusUpdateListener((st: { status: number }) => {
            const DOWNLOADED = mod.IAUInstallStatus?.DOWNLOADED ?? 11;
            if (st.status === DOWNLOADED) void updater.installUpdate();
          });
          await updater.startUpdate({ updateType: mod.IAUUpdateKind.FLEXIBLE });
        }
      } catch {
        // fail open: non-Play installs fall back to the backend UpdateBanner
      } finally {
        busy.current = false;
      }
    };

    void run();
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") void run();
    });
    return () => sub.remove();
  }, []);

  return null;
}
