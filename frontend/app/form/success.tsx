import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { CheckCircle2, CloudOff, Home } from "lucide-react-native";
import React, { useEffect } from "react";
import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { colors, fonts, sizes, spacing, type } from "@/src/theme/tokens";

export default function FormSuccess() {
  const router = useRouter();
  const { t } = useTranslation();
  const { queued } = useLocalSearchParams<{ queued: string; rid?: string }>();
  const isQueued = queued === "1";

  useEffect(() => {
    void Haptics.notificationAsync(
      isQueued ? Haptics.NotificationFeedbackType.Warning : Haptics.NotificationFeedbackType.Success,
    ).catch(() => undefined);
    const timer = setTimeout(() => router.replace("/(tabs)/department"), 4000);
    return () => clearTimeout(timer);
  }, [isQueued, router]);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="form-success-screen">
      <ScreenHeader title={t("forms.title")} backTo="/(tabs)/department" />
      <View style={styles.content}>
        <View style={styles.center}>
          <View
            style={[styles.circle, { backgroundColor: isQueued ? "#FDF0DC" : "#DDF5E5" }]}
            testID={isQueued ? "form-queued-icon" : "form-sent-icon"}
          >
            {isQueued ? (
              <CloudOff size={64} color={colors.warning} strokeWidth={2} />
            ) : (
              <CheckCircle2 size={64} color={colors.success} strokeWidth={2} />
            )}
          </View>
          <Text style={styles.title}>
            {isQueued ? t("incident.queuedTitle") : t("forms.successTitle")}
          </Text>
          <Text style={styles.body}>
            {isQueued ? t("incident.queuedBody") : t("forms.successBody")}
          </Text>
          <Text style={styles.returning}>{t("incident.returningHome")}</Text>
        </View>
        <BigButton
          testID="form-success-home-button"
          label={t("common.home")}
          icon={Home}
          height={64}
          onPress={() => router.replace("/(tabs)/department")}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: {
    flex: 1,
    padding: sizes.screenPadding,
    justifyContent: "space-between",
    paddingBottom: spacing.xl,
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  circle: {
    width: 140,
    height: 140,
    borderRadius: 70,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  title: { fontFamily: fonts.bold, fontSize: type.xxl, color: colors.text, textAlign: "center" },
  body: { fontFamily: fonts.regular, fontSize: type.lg, color: colors.muted, textAlign: "center" },
  returning: {
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
    marginTop: spacing.xl,
  },
});
