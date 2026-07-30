import { useRouter } from "expo-router";
import { AlertTriangle, Clock, LogOut, RefreshCcw } from "lucide-react-native";
import React, { useCallback, useEffect } from "react";
import { AppState, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { showToast } from "@/src/components/Toast";
import { SpeakerButton } from "@/src/components/SpeakerButton";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, sizes, spacing, type } from "@/src/theme/tokens";

export default function PendingApproval() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const refreshProfile = useAuthStore((s) => s.refreshProfile);
  const logout = useAuthStore((s) => s.logout);

  const check = useCallback(async () => {
    const fresh = await refreshProfile();
    if (fresh && fresh.onboarding_status === "approved") {
      showToast(t("common.done"), "success");
      router.replace("/"); // via index gate → permission primer runs after approval
    }
  }, [refreshProfile, router, t]);

  // poll on app foreground to detect approval
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") void check();
    });
    const interval = setInterval(() => void check(), 30000);
    return () => {
      sub.remove();
      clearInterval(interval);
    };
  }, [check]);

  return (
    <SafeAreaView style={styles.safe} testID="pending-approval-screen">
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.iconCircle}>
          <Clock size={44} color={colors.warning} strokeWidth={2.2} />
        </View>
        <Text style={styles.title}>{t("reg.pendingTitle")}</Text>
        <Text style={styles.name}>{profile?.full_name}</Text>
        <Text style={styles.body}>{t("reg.pendingBody")}</Text>
        <SpeakerButton
          text={`${t("reg.pendingTitle")}. ${t("reg.pendingBody")}`}
          testID="pending-tts"
          style={{ marginTop: spacing.sm }}
        />

        <View style={styles.actions}>
          <BigButton
            testID="pending-report-incident-button"
            label={t("reg.pendingIncident")}
            icon={AlertTriangle}
            variant="danger"
            height={72}
            onPress={() => router.push("/incident/capture")}
          />
          <BigButton
            testID="pending-check-status-button"
            label={t("reg.checkStatus")}
            icon={RefreshCcw}
            variant="outline"
            onPress={() => void check()}
          />
          <BigButton
            testID="pending-logout-button"
            label={t("common.logout")}
            icon={LogOut}
            variant="muted"
            onPress={() => {
              void logout().then(() => router.replace("/(auth)/phone"));
            }}
          />
        </View>
      </ScrollView>
      </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: {
    padding: sizes.screenPadding,
    flexGrow: 1,
    justifyContent: "center",
    alignItems: "stretch",
  },
  iconCircle: {
    alignSelf: "center",
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: "#FDF0DC",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  title: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
    textAlign: "center",
  },
  name: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.primary,
    textAlign: "center",
    marginTop: spacing.xs,
  },
  body: {
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.md,
    marginBottom: spacing.xl,
  },
  actions: { gap: spacing.md },
});
