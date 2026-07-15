import dayjs from "dayjs";
import * as Haptics from "expo-haptics";
import { useFocusEffect, useRouter } from "expo-router";
import {
  AlertTriangle,
  Bell,
  CalendarDays,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  LogIn,
  LogOut,
} from "lucide-react-native";
import React, { useCallback, useEffect, useState } from "react";
import { Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { myAttendance, myIncidents, myNotifications, myShifts, punchOut } from "@/src/api/endpoints";
import type { AttendanceRecord, Incident, NotificationList, ShiftDay } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { ConfirmModal } from "@/src/components/ConfirmModal";
import { GridTile } from "@/src/components/GridTile";
import { showToast } from "@/src/components/Toast";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { useNotifStore } from "@/src/stores/notifStore";
import { colors, fonts, radius, shadow, sizes, spacing, type } from "@/src/theme/tokens";
import { formatShiftTime, formatTime } from "@/src/utils/format";

export default function HomeScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const setUnread = useNotifStore((s) => s.setUnread);
  const unread = useNotifStore((s) => s.unread);
  const outboxCount = useOutboxStore((s) => s.items.length);
  const [confirmOut, setConfirmOut] = useState(false);
  const [punchingOut, setPunchingOut] = useState(false);

  const month = dayjs().format("YYYY-MM");
  const att = useCachedFetch<AttendanceRecord[]>(`att-${month}`, () => myAttendance(month));
  const shifts = useCachedFetch<ShiftDay[]>("shifts", myShifts);
  const notifs = useCachedFetch<NotificationList>("notifs", myNotifications);
  const incidents = useCachedFetch<Incident[]>("incidents-mine", myIncidents);

  useEffect(() => {
    if (notifs.data) setUnread(notifs.data.unread_count);
  }, [notifs.data, setUnread]);

  useFocusEffect(
    useCallback(() => {
      void att.refresh();
      void notifs.refresh();
      void incidents.refresh();
      // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh fns are stable per key
    }, []),
  );

  const rank = profile?.role?.rank ?? 6;
  const eligible = profile?.shift_swap_eligible ?? false;
  const today = dayjs().format("YYYY-MM-DD");
  const todayRec = att.data?.find((r) => r.date === today) ?? null;
  const todayShift = shifts.data?.[0] ?? null;

  // My Reports strip: last 7 days summary
  const weekAgo = dayjs().subtract(7, "day");
  const recentReports = (incidents.data ?? []).filter(
    (i) => i.created_at && dayjs(i.created_at).isAfter(weekAgo),
  );
  const openCount = recentReports.filter((i) => i.status !== "resolved").length;
  const resolvedCount = recentReports.filter((i) => i.status === "resolved").length;
  const stripText = [
    openCount > 0 ? t("home.stripOpen", { count: openCount }) : null,
    resolvedCount > 0 ? t("home.stripResolved", { count: resolvedCount }) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const doPunchOut = async () => {
    setConfirmOut(false);
    setPunchingOut(true);
    try {
      await punchOut();
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      await att.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else showToast(t("errors.server"), "error");
    } finally {
      setPunchingOut(false);
    }
  };

  const attendanceBody = () => {
    if (!todayRec) {
      return (
        <>
          <Text style={styles.attState}>{t("att.notPunched")}</Text>
          <BigButton
            testID="punch-in-button"
            label={t("home.punchIn")}
            icon={LogIn}
            variant="success"
            height={64}
            onPress={() => router.push("/attendance/punch")}
          />
        </>
      );
    }
    if (!todayRec.punch_out_at) {
      return (
        <>
          <View style={styles.attRow}>
            <Text style={styles.attState}>
              {t("home.onDuty", { time: formatTime(todayRec.punch_in_at) })}
            </Text>
            {todayRec.is_late ? (
              <View style={styles.lateChip}>
                <Text style={styles.lateChipText}>{t("att.late")}</Text>
              </View>
            ) : null}
          </View>
          <BigButton
            testID="punch-out-button"
            label={t("home.punchOut")}
            icon={LogOut}
            variant="outline"
            loading={punchingOut}
            onPress={() => setConfirmOut(true)}
          />
        </>
      );
    }
    return (
      <Text style={styles.attState}>
        {t("home.punchedOut")} · {formatTime(todayRec.punch_in_at)} – {formatTime(todayRec.punch_out_at)}
      </Text>
    );
  };

  const initials = (profile?.full_name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} testID="home-screen">
      <View style={styles.brandHeader}>
        <View style={styles.brandRow}>
          <View style={styles.brandSpacer} />
          <View style={styles.brandCenter} testID="home-brand">
            <Image
              source={require("@/assets/images/logo.png")}
              style={styles.brandLogo}
              resizeMode="contain"
            />
            <Text style={styles.brandName}>HogoPlus-FS</Text>
          </View>
          <Pressable
            testID="home-avatar"
            accessibilityRole="button"
            onPress={() => router.push("/(tabs)/profile")}
            style={styles.avatar}
          >
            <Text style={styles.avatarText}>{initials || "?"}</Text>
          </Pressable>
        </View>
        <View style={styles.subRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.headerName} numberOfLines={1}>
              {t("home.hello")}, {profile?.full_name}
            </Text>
            <Text style={styles.headerSub} numberOfLines={1}>
              {dayjs().format("DD/MM/YYYY")}
              {profile?.department ? ` · ${tri(profile.department as unknown as Record<string, unknown>, "name")}` : ""}
            </Text>
          </View>
          {eligible && todayShift?.shift_code ? (
            <View style={styles.shiftChip} testID="today-shift-chip">
              <Text style={styles.shiftChipCode}>{todayShift.shift_code}</Text>
              <Text style={styles.shiftChipTime}>
                {formatShiftTime(todayShift.start_time)}
              </Text>
            </View>
          ) : null}
        </View>
      </View>
      <ScrollView
        style={styles.scrollBg}
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={false}
            onRefresh={() => {
              void att.refresh();
              void shifts.refresh();
              void notifs.refresh();
            }}
            tintColor={colors.primary}
          />
        }
      >
        <Pressable
          testID="report-incident-tile"
          accessibilityRole="button"
          onPress={() => {
            void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => undefined);
            router.push("/incident/capture");
          }}
          style={({ pressed }) => [styles.incidentTile, { opacity: pressed ? 0.9 : 1 }]}
        >
          <View style={styles.incidentIconWrap}>
            <AlertTriangle size={44} color={colors.onDanger} strokeWidth={2.4} />
          </View>
          <Text style={styles.incidentLabel}>{t("home.reportIncident")}</Text>
        </Pressable>

        {stripText ? (
          <Pressable
            testID="reports-strip"
            accessibilityRole="button"
            onPress={() => router.push("/(tabs)/reports")}
            style={({ pressed }) => [styles.strip, { opacity: pressed ? 0.85 : 1 }]}
          >
            <Text style={styles.stripText} numberOfLines={1}>
              {stripText}
            </Text>
            <ChevronRight size={20} color={colors.accent} strokeWidth={2.4} />
          </Pressable>
        ) : null}

        <View style={[styles.attCard, shadow.card]} testID="attendance-card">
          <View style={styles.attHead}>
            <Text style={styles.attTitle}>{t("att.title")}</Text>
            <Pressable
              testID="attendance-history-link"
              onPress={() => router.push("/attendance/history")}
              style={styles.historyLink}
            >
              <Text style={styles.historyLinkText}>{t("att.viewHistory")}</Text>
            </Pressable>
          </View>
          {attendanceBody()}
        </View>

        <View style={styles.grid}>
          <GridTile
            testID="home-tile-reports"
            label={t("home.myReports")}
            icon={ClipboardList}
            badge={outboxCount}
            onPress={() => router.push("/(tabs)/reports")}
          />
          {eligible ? (
            <GridTile
              testID="home-tile-shift"
              label={t("home.myShift")}
              icon={CalendarDays}
              tint={colors.accent}
              onPress={() => router.push("/shift")}
            />
          ) : (
            <GridTile
              testID="home-tile-alerts"
              label={t("home.notifications")}
              icon={Bell}
              badge={unread}
              tint={colors.warning}
              onPress={() => router.push("/(tabs)/alerts")}
            />
          )}
        </View>
        {eligible || rank <= 3 ? (
          <View style={styles.grid}>
            {eligible ? (
              <GridTile
                testID="home-tile-alerts"
                label={t("home.notifications")}
                icon={Bell}
                badge={unread}
                tint={colors.warning}
                onPress={() => router.push("/(tabs)/alerts")}
              />
            ) : null}
            {rank <= 3 ? (
              <GridTile
                testID="home-tile-approvals"
                label={t("home.approvals")}
                icon={ClipboardCheck}
                tint={colors.success}
                onPress={() => router.push("/(tabs)/approvals")}
              />
            ) : null}
            {(eligible ? 1 : 0) + (rank <= 3 ? 1 : 0) === 1 ? <View style={{ flex: 1 }} /> : null}
          </View>
        ) : null}
      </ScrollView>

      <ConfirmModal
        visible={confirmOut}
        title={t("att.confirmPunchOut")}
        confirmLabel={t("home.punchOut")}
        onConfirm={() => void doPunchOut()}
        onCancel={() => setConfirmOut(false)}
        testIDPrefix="punch-out"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.primary },
  scrollBg: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.lg, paddingBottom: spacing.xxl },
  brandHeader: {
    backgroundColor: colors.primary,
    paddingHorizontal: sizes.screenPadding,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  brandRow: { flexDirection: "row", alignItems: "center" },
  brandSpacer: { width: 44 },
  brandCenter: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
  },
  brandLogo: { width: 36, height: 30 },
  brandName: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.onPrimary },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: "rgba(255,255,255,0.22)",
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.onPrimary },
  subRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  headerName: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.onPrimary },
  headerSub: { fontFamily: fonts.medium, fontSize: type.sm, color: "rgba(255,255,255,0.8)" },
  shiftChip: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    alignItems: "center",
  },
  shiftChipCode: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.primary },
  shiftChipTime: { fontFamily: fonts.medium, fontSize: 12, color: colors.primary },
  incidentTile: {
    minHeight: sizes.incidentTile,
    backgroundColor: colors.danger,
    borderRadius: radius.lg,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.lg,
    paddingHorizontal: spacing.xl,
  },
  incidentIconWrap: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: "rgba(255,255,255,0.18)",
    alignItems: "center",
    justifyContent: "center",
  },
  incidentLabel: {
    flex: 1,
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.onDanger,
  },
  attCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  attHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  attTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  historyLink: { minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.sm },
  historyLinkText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.accent },
  attRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  attState: { fontFamily: fonts.medium, fontSize: type.base, color: colors.text },
  lateChip: {
    backgroundColor: colors.warning,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 2,
  },
  lateChipText: { fontFamily: fonts.semiBold, fontSize: 12, color: colors.onWarning },
  grid: { flexDirection: "row", gap: spacing.md },
  strip: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
    minHeight: 48,
    marginTop: -spacing.xs,
  },
  stripText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.accent, flex: 1 },
});
