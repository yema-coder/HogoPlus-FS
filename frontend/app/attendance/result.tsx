import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { CheckCircle2, CloudOff, Flag, Home, ShieldCheck } from "lucide-react-native";
import React, { useEffect, useRef, useState } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { myAttendance, sendBleDiag } from "@/src/api/endpoints";
import { BigButton } from "@/src/components/BigButton";
import { showToast } from "@/src/components/Toast";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatTime } from "@/src/utils/format";
import { storage } from "@/src/utils/storage";

export default function PunchResultScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const { queued, level, zone, late, time, addr, coords } = useLocalSearchParams<{
    queued: string;
    level: string;
    zone: string;
    late: string;
    time: string;
    addr: string;
    coords: string;
  }>();

  const isQueued = queued === "1";

  // Prompt 16: dignified 0.6s tick pop + attendance streak
  const scale = useRef(new Animated.Value(0.4)).current;
  const [streak, setStreak] = useState<{ days: number; total: number } | null>(null);
  useEffect(() => {
    Animated.spring(scale, {
      toValue: 1,
      friction: 4,
      tension: 60,
      useNativeDriver: true,
    }).start();
    if (!isQueued) {
      void myAttendance(new Date().toISOString().slice(0, 7))
        .then((rows) => setStreak({ days: rows.length, total: new Date().getDate() }))
        .catch(() => undefined);
    }
  }, [scale, isQueued]);

  useEffect(() => {
    void Haptics.notificationAsync(
      isQueued || level === "flagged"
        ? Haptics.NotificationFeedbackType.Warning
        : Haptics.NotificationFeedbackType.Success,
    ).catch(() => undefined);
  }, [isQueued, level]);

  const render = () => {
    if (isQueued) {
      return {
        icon: <CloudOff size={64} color={colors.warning} strokeWidth={2} />,
        bg: "#FDF0DC",
        title: t("incident.queuedTitle"),
        body: t("att.queuedBody"),
        testID: "punch-result-queued",
      };
    }
    if (level === "verified_plus") {
      return {
        icon: <ShieldCheck size={64} color={colors.success} strokeWidth={2} />,
        bg: "#DDF5E5",
        title: t("att.verifiedPlus"),
        body: zone ? t("att.verifiedPlusDesc", { zone }) : t("att.verifiedDesc"),
        testID: "punch-result-verified-plus",
      };
    }
    if (level === "verified") {
      return {
        icon: <CheckCircle2 size={64} color={colors.success} strokeWidth={2} />,
        bg: "#DDF5E5",
        title: t("att.verified"),
        body: t("att.verifiedDesc"),
        testID: "punch-result-verified",
      };
    }
    return {
      icon: <Flag size={64} color={colors.warning} strokeWidth={2} />,
      bg: "#FDF0DC",
      title: t("att.flagged"),
      body: t("att.flaggedDesc"),
      testID: "punch-result-flagged",
    };
  };

  const r = render();

  return (
    <SafeAreaView style={styles.safe} testID="punch-result-screen">
      <View style={styles.center}>
        <Animated.View
          style={[styles.circle, { backgroundColor: r.bg, transform: [{ scale }] }]}
          testID={r.testID}
        >
          {r.icon}
        </Animated.View>
        <Text style={styles.title}>{r.title}</Text>
        <Text style={styles.body}>{r.body}</Text>
        {streak && streak.days > 0 ? (
          <View style={styles.streakChip} testID="punch-streak-chip">
            <Text style={styles.streakText}>
              🔥 {t("today.streak", { days: streak.days, total: streak.total })}
            </Text>
          </View>
        ) : null}
        {!isQueued && time ? (
          <Text style={styles.time}>
            {t("att.punchedInAt")}: {formatTime(time)}
          </Text>
        ) : null}
        {!isQueued ? (
          <View
            style={[
              styles.lateChip,
              { backgroundColor: late === "1" ? colors.warning : colors.success },
            ]}
            testID={late === "1" ? "punch-late-chip" : "punch-ontime-chip"}
          >
            <Text
              style={[
                styles.lateChipText,
                { color: late === "1" ? colors.onWarning : colors.onSuccess },
              ]}
            >
              {late === "1" ? t("att.late") : t("att.onTime")}
            </Text>
          </View>
        ) : null}
        {!isQueued && (zone || addr || coords) ? (
          <View style={styles.locationBlock} testID="punch-location-block">
            <Text style={styles.locationLabel}>📍 {t("common.location")}</Text>
            {zone ? <Text style={styles.locationZone}>{zone}</Text> : null}
            {addr ? <Text style={styles.locationAddr}>{addr}</Text> : null}
            {coords ? <Text style={styles.locationCoords}>{coords}</Text> : null}
          </View>
        ) : null}
        {!isQueued ? (
          <Text
            testID="share-timings-button"
            accessibilityRole="button"
            style={styles.shareLink}
            onPress={() => {
              void (async () => {
                try {
                  const raw = await storage.getItem("hogo.lastPunchTimings");
                  await sendBleDiag({
                    kind: "punch_timing_card",
                    timings: raw ? JSON.parse(raw) : null,
                    zone: zone || null,
                    level: level || null,
                    shared_at: new Date().toISOString(),
                  });
                  showToast(t("att.timingsShared"), "success");
                } catch {
                  showToast(t("errors.server"), "error");
                }
              })();
            }}
          >
            📤 {t("att.shareTimings")}
          </Text>
        ) : null}
      </View>
      <BigButton
        testID="result-home-button"
        label={t("common.home")}
        icon={Home}
        height={64}
        onPress={() => router.replace("/(tabs)/home")}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
    padding: sizes.screenPadding,
    justifyContent: "space-between",
    paddingBottom: spacing.xl,
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  shareLink: {
    marginTop: spacing.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.primary,
  },
  locationBlock: {
    alignItems: "center",
    gap: 2,
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    alignSelf: "stretch",
  },
  locationLabel: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.muted },
  locationZone: { fontFamily: fonts.bold, fontSize: type.base, color: colors.primary },
  locationAddr: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.text, textAlign: "center" },
  locationCoords: { fontFamily: fonts.regular, fontSize: 12, color: colors.muted },
  circle: {
    width: 140,
    height: 140,
    borderRadius: 70,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  title: { fontFamily: fonts.bold, fontSize: type.xxl, color: colors.text, textAlign: "center" },
  body: {
    fontFamily: fonts.regular,
    fontSize: type.lg,
    color: colors.muted,
    textAlign: "center",
  },
  time: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.primary },
  lateChip: {
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
    marginTop: spacing.md,
  },
  lateChipText: { fontFamily: fonts.bold, fontSize: type.base },
  streakChip: {
    backgroundColor: "#DDF5E5",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: 6,
    marginTop: spacing.sm,
  },
  streakText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.success },
});
