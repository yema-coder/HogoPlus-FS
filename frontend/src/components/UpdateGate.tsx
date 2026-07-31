/**
 * v1.0.17 — Google Play In-App Updates gate (item 4).
 * On app open (and each foreground return) checks the backend's app-version row;
 * when a newer version exists, runs the native Play in-app update flow:
 *   - FLEXIBLE by default (background download, auto-install when done)
 *   - IMMEDIATE (blocking full-screen) when the backend row has force_update=true
 *
 * v1.0.22 — force_update BLOCK SCREEN (owner requirement: "never a dead end").
 * When force_update=true and the Play IMMEDIATE flow is unavailable (sideloaded
 * install, phone outside the Play internal-testing list), a full-screen
 * non-dismissible modal takes over with a WORKING path out:
 *   1. "Update now" → the admin-set apk_url, else the Play store listing
 *   2. clear instructions + support contact (Time Office) if neither works
 *   3. "I've updated — check again" re-checks (also re-checks on every foreground)
 * Non-force updates keep the old fail-open behavior (banner fallback, no blocking).
 */
import Constants from "expo-constants";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Linking, Modal, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { getAppVersion } from "@/src/api/endpoints";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

function isNewer(latest: string, current: string): boolean {
  // SEMANTIC comparison — numeric per dot-segment ("1.0.18" > "1.0.9"),
  // never a string compare.
  const a = latest.split(".").map((n) => parseInt(n, 10) || 0);
  const b = current.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) > (b[i] ?? 0)) return true;
    if ((a[i] ?? 0) < (b[i] ?? 0)) return false;
  }
  return false;
}

const CURRENT = Constants.expoConfig?.version ?? "0.0.0";
const PACKAGE = Constants.expoConfig?.android?.package ?? "com.hogoplus.fs";

export function UpdateGate() {
  const { t } = useTranslation();
  const busy = useRef(false);
  const [block, setBlock] = useState<{ latest: string; notes: string | null; url: string | null } | null>(null);

  const run = useCallback(async () => {
    // Native flow + block screen: Android builds only (web/Expo Go/iOS fail open —
    // the dismissible UpdateBanner covers those surfaces)
    if (Platform.OS !== "android" || Constants.appOwnership === "expo") return;
    if (busy.current) return;
    busy.current = true;
    try {
      const info = await getAppVersion();
      if (!info.latest_version || !isNewer(info.latest_version, CURRENT)) {
        setBlock(null); // covers "user updated then returned to foreground"
        return;
      }
      let playHandled = false;
      try {
        // lazy require: keeps Expo Go/web bundles from touching the native module
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const mod = require("sp-react-native-in-app-updates");
        const SpInAppUpdates = mod.default ?? mod;
        const updater = new SpInAppUpdates(false);
        const check = await updater.checkNeedsUpdate({ curVersion: CURRENT });
        if (check?.shouldUpdate) {
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
          playHandled = true;
        }
      } catch {
        // Play unavailable (sideloaded APK / not in the testing list) — fall through
      }
      if (info.force_update && !playHandled) {
        setBlock({
          latest: info.latest_version,
          notes: info.notes ?? null,
          url: info.apk_url ?? null,
        });
      }
    } catch {
      // version check must never break the app
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    void run();
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") void run();
    });
    return () => sub.remove();
  }, [run]);

  if (!block) return null;

  const openUpdate = () => {
    const target = block.url ?? `market://details?id=${PACKAGE}`;
    Linking.openURL(target).catch(() => {
      // market:// missing (no Play) → web listing as the last resort
      void Linking.openURL(`https://play.google.com/store/apps/details?id=${PACKAGE}`).catch(() => undefined);
    });
  };

  return (
    <Modal visible transparent={false} animationType="fade" onRequestClose={() => undefined}>
      <View style={styles.wrap} testID="force-update-screen">
        <Text style={styles.emoji}>⬆️</Text>
        <Text style={styles.title}>{t("update.requiredTitle")}</Text>
        <Text style={styles.body}>
          {t("update.requiredBody", { latest: block.latest, current: CURRENT })}
        </Text>
        {block.notes ? <Text style={styles.notes}>{block.notes}</Text> : null}
        <Pressable style={styles.btn} onPress={openUpdate} testID="force-update-open" accessibilityRole="button">
          <Text style={styles.btnText}>{t("update.updateNow")}</Text>
        </Pressable>
        <Text style={styles.help}>{t("update.noLink")}</Text>
        <Pressable style={styles.retry} onPress={() => void run()} testID="force-update-recheck" accessibilityRole="button">
          <Text style={styles.retryText}>{t("update.retry")}</Text>
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
  },
  emoji: { fontSize: 56 },
  title: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.text, textAlign: "center" },
  body: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted, textAlign: "center" },
  notes: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, textAlign: "center", fontStyle: "italic" },
  btn: {
    backgroundColor: colors.primary,
    borderRadius: radius.lg,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xl,
    minHeight: 52,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "stretch",
    marginTop: spacing.md,
  },
  btnText: { fontFamily: fonts.bold, fontSize: type.base, color: "#fff" },
  help: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, textAlign: "center", marginTop: spacing.sm },
  retry: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  retryText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.primary },
});
