import { useCameraPermissions } from "expo-camera";
import * as Location from "expo-location";
import { useRouter } from "expo-router";
import { Bell, Camera, MapPin } from "lucide-react-native";
import React, { useState } from "react";
import { Image, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { requestNotificationPermissionsSafe } from "@/src/notifications/safeNotifications";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/** One-time post-login permission priming: explains why, then triggers the
 * system dialogs sequentially. Every deny is non-blocking — downstream screens
 * degrade gracefully (camera screens show Open Settings, GPS-off flags punch). */
export default function PermissionsPrimer() {
  const router = useRouter();
  const { t } = useTranslation();
  const markPermsPrimed = useAuthStore((s) => s.markPermsPrimed);
  const [, requestCamera] = useCameraPermissions();
  const [busy, setBusy] = useState(false);

  const allow = async () => {
    setBusy(true);
    try {
      await requestCamera();
    } catch {
      // never block onboarding on a permission error
    }
    try {
      await Location.requestForegroundPermissionsAsync();
    } catch {
      // ignore
    }
    // lazy + guarded: silent no-op where the push native module is absent (Expo Go iOS / web)
    await requestNotificationPermissionsSafe();
    await markPermsPrimed();
    router.replace("/(tabs)/home");
  };

  const cards = [
    { icon: Camera, title: t("perm.cameraTitle"), body: t("perm.cameraBody"), tid: "perm-card-camera" },
    { icon: MapPin, title: t("perm.locationTitle"), body: t("perm.locationBody"), tid: "perm-card-location" },
    { icon: Bell, title: t("perm.notifTitle"), body: t("perm.notifBody"), tid: "perm-card-notifications" },
  ];

  return (
    <SafeAreaView style={styles.safe} testID="permissions-screen">
      <ScrollView contentContainerStyle={styles.scroll}>
        <Image
          source={require("@/assets/images/logo.png")}
          style={styles.logo}
          resizeMode="contain"
        />
        <Text style={styles.title}>{t("perm.title")}</Text>
        <Text style={styles.subtitle}>{t("perm.subtitle")}</Text>
        {cards.map((c) => (
          <View key={c.tid} style={styles.card} testID={c.tid}>
            <View style={styles.iconWrap}>
              <c.icon size={28} color={colors.primary} strokeWidth={2.2} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardTitle}>{c.title}</Text>
              <Text style={styles.cardBody}>{c.body}</Text>
            </View>
          </View>
        ))}
      </ScrollView>
      <View style={styles.footer}>
        <BigButton
          testID="perm-allow-button"
          label={t("perm.allow")}
          loading={busy}
          onPress={() => void allow()}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md, alignItems: "stretch" },
  logo: { width: 96, height: 78, alignSelf: "center", marginTop: spacing.xl },
  title: {
    fontFamily: fonts.bold,
    fontSize: type.xxl,
    color: colors.text,
    textAlign: "center",
    marginTop: spacing.md,
  },
  subtitle: {
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
    textAlign: "center",
    marginBottom: spacing.lg,
  },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.lg,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  iconWrap: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  cardTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  cardBody: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  footer: { padding: sizes.screenPadding },
});
