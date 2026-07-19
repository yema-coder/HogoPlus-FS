import Constants from "expo-constants";
import { Download, X } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { getAppVersion } from "@/src/api/endpoints";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";
import { storage } from "@/src/utils/storage";

const CHECK_KEY = "hogo.versionCheck"; // {date, latest, url}

function isNewer(latest: string, current: string): boolean {
  const a = latest.split(".").map((n) => parseInt(n, 10) || 0);
  const b = current.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) > (b[i] ?? 0);
  }
  return false;
}

/** Slim dismissible "update available" banner. Checks GET /app-version at most
 * once per day (cached in AsyncStorage) and compares against the app's own version. */
export function UpdateBanner() {
  const { t } = useTranslation();
  const [info, setInfo] = useState<{ latest: string; url: string | null } | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const current = Constants.expoConfig?.version ?? "0.0.0";
    const today = new Date().toISOString().slice(0, 10);
    void (async () => {
      try {
        const cached = await storage.getItem<string>(CHECK_KEY, "");
        let latest: string | null = null;
        let url: string | null = null;
        if (cached) {
          const parsed = JSON.parse(String(cached)) as { date: string; latest: string | null; url: string | null };
          if (parsed.date === today) {
            latest = parsed.latest;
            url = parsed.url;
          }
        }
        if (latest === null) {
          const res = await getAppVersion();
          latest = res.latest_version;
          url = res.apk_url;
          await storage.setItem(CHECK_KEY, JSON.stringify({ date: today, latest, url }));
        }
        if (latest && isNewer(latest, current)) setInfo({ latest, url });
      } catch {
        // version check must never disturb the app
      }
    })();
  }, []);

  if (!info || dismissed) return null;
  return (
    <View style={styles.banner} testID="update-banner">
      <Download size={16} color={colors.primary} strokeWidth={2.4} />
      <Pressable
        style={{ flex: 1, minHeight: 44, justifyContent: "center" }}
        accessibilityRole="button"
        testID="update-banner-link"
        onPress={() => {
          if (info.url) void Linking.openURL(info.url).catch(() => undefined);
        }}
      >
        <Text style={styles.text} numberOfLines={2}>
          {t("update.banner", { version: info.latest })}
        </Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        testID="update-banner-dismiss"
        onPress={() => setDismissed(true)}
        style={styles.close}
      >
        <X size={18} color={colors.muted} strokeWidth={2.4} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.primary,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
  },
  text: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.primary },
  close: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
});
