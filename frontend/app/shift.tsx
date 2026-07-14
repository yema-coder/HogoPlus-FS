import dayjs from "dayjs";
import { Redirect, useFocusEffect, useRouter } from "expo-router";
import { ArrowLeftRight, CalendarX2 } from "lucide-react-native";
import React, { useCallback, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { cancelSwap, myShifts, mySwaps, respondSwap } from "@/src/api/endpoints";
import type { ShiftDay, SwapRequest } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatShiftTime } from "@/src/utils/format";

const SWAP_STATUS_COLORS: Record<string, string> = {
  pending_target: colors.warning,
  pending_manager: colors.accent,
  approved: colors.success,
  rejected: colors.danger,
  cancelled: colors.muted,
};

export default function ShiftScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const { data, loading, error, refresh } = useCachedFetch<ShiftDay[]>("shifts", myShifts);
  const swaps = useCachedFetch<SwapRequest[]>("swaps-mine", mySwaps);
  const [acting, setActing] = useState(false);

  useFocusEffect(
    useCallback(() => {
      void refresh();
      void swaps.refresh();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []),
  );

  // shift UI is only for swap-eligible employees (Workers + SECURITY)
  if (profile && !profile.shift_swap_eligible) {
    return <Redirect href="/(tabs)/home" />;
  }

  const incoming = (swaps.data ?? []).filter(
    (s) => s.target_id === profile?.id && s.status === "pending_target",
  );
  const outgoing = (swaps.data ?? []).filter((s) => s.requester_id === profile?.id);

  const respond = async (swap: SwapRequest, accept: boolean) => {
    if (acting) return;
    setActing(true);
    try {
      await respondSwap(swap.id, accept);
      showToast(t("approvals.actionDone"), "success");
      await Promise.all([swaps.refresh(), refresh()]);
    } catch (e) {
      showToast(e instanceof ApiError && e.status === 0 ? t("errors.network") : t("errors.server"), "error");
    } finally {
      setActing(false);
    }
  };

  const cancel = async (swap: SwapRequest) => {
    if (acting) return;
    setActing(true);
    try {
      await cancelSwap(swap.id);
      showToast(t("swap.cancelled"), "info");
      await Promise.all([swaps.refresh(), refresh()]);
    } catch (e) {
      showToast(e instanceof ApiError && e.status === 0 ? t("errors.network") : t("errors.server"), "error");
    } finally {
      setActing(false);
    }
  };

  const dayLabel = (dateStr: string, index: number): string => {
    if (index === 0) return t("common.today");
    if (index === 1) return t("common.tomorrow");
    const d = dayjs(dateStr);
    return `${t(`week.d${d.day()}`)} ${d.format("DD/MM")}`;
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="shift-screen">
      <ScreenHeader title={t("shift.title")} />
      {error && !data ? (
        <ErrorRetry onRetry={() => void refresh()} />
      ) : (
        <ScrollView contentContainerStyle={styles.list}>
          {incoming.map((s) => (
            <View key={s.id} style={styles.incomingCard} testID={`incoming-swap-${s.id}`}>
              <Text style={styles.incomingTitle}>
                {t("swap.incomingTitle", { name: s.requester_name ?? "" })}
              </Text>
              <Text style={styles.incomingMeta}>
                {dayjs(s.swap_date).format("DD/MM/YYYY")} · {t("att.shift")}{" "}
                {s.requester_shift_code ?? "—"} ⇄ {s.target_shift_code ?? "—"}
              </Text>
              {s.reason ? <Text style={styles.incomingMeta}>{s.reason}</Text> : null}
              <View style={styles.actionRow}>
                <BigButton
                  testID={`swap-decline-${s.id}`}
                  label={t("swap.decline")}
                  variant="danger"
                  disabled={acting}
                  onPress={() => void respond(s, false)}
                  style={{ flex: 1 }}
                />
                <BigButton
                  testID={`swap-accept-${s.id}`}
                  label={t("swap.accept")}
                  variant="success"
                  disabled={acting}
                  onPress={() => void respond(s, true)}
                  style={{ flex: 1 }}
                />
              </View>
            </View>
          ))}

          <BigButton
            testID="swap-shift-button"
            label={t("swap.button")}
            icon={ArrowLeftRight}
            variant="accent"
            onPress={() => router.push("/swap/new")}
          />

          {(data ?? []).length === 0 && !loading ? (
            <EmptyState icon={CalendarX2} title={t("shift.noShift")} />
          ) : (
            (data ?? []).map((item, index) => (
              <View
                key={item.date}
                style={[styles.row, index === 0 && styles.rowToday]}
                testID={`shift-row-${item.date}`}
              >
                <View style={{ flex: 1 }}>
                  <Text style={[styles.day, index === 0 && { color: colors.primary }]}>
                    {dayLabel(item.date, index)}
                  </Text>
                  <Text style={styles.time}>
                    {item.shift_code
                      ? `${formatShiftTime(item.start_time)} – ${formatShiftTime(item.end_time)}`
                      : t("shift.noShift")}
                  </Text>
                </View>
                {item.shift_code ? (
                  <View style={styles.codeCircle}>
                    <Text style={styles.codeText}>{item.shift_code}</Text>
                  </View>
                ) : null}
              </View>
            ))
          )}

          {outgoing.length > 0 ? (
            <>
              <Text style={styles.sectionTitle}>{t("swap.myRequests")}</Text>
              {outgoing.map((s) => (
                <View key={s.id} style={styles.swapReqRow} testID={`my-swap-${s.id}`}>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={styles.swapReqTitle}>
                      {dayjs(s.swap_date).format("DD/MM/YYYY")} · {s.target_name ?? ""}
                    </Text>
                    <View
                      style={[
                        styles.swapStatusChip,
                        { backgroundColor: SWAP_STATUS_COLORS[s.status] ?? colors.muted },
                      ]}
                    >
                      <Text style={styles.swapStatusText}>{t(`swap.${s.status}`)}</Text>
                    </View>
                  </View>
                  {s.status === "pending_target" || s.status === "pending_manager" ? (
                    <Pressable
                      testID={`swap-cancel-${s.id}`}
                      onPress={() => void cancel(s)}
                      style={styles.cancelBtn}
                    >
                      <Text style={styles.cancelText}>{t("swap.cancel")}</Text>
                    </Pressable>
                  ) : null}
                </View>
              ))}
            </>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  list: { padding: sizes.screenPadding, gap: spacing.md, flexGrow: 1 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    minHeight: 76,
  },
  rowToday: { borderColor: colors.primary, borderWidth: 2 },
  day: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  time: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted },
  codeCircle: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  codeText: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.primary },
  sectionTitle: {
    fontFamily: fonts.bold,
    fontSize: type.lg,
    color: colors.text,
    marginTop: spacing.md,
  },
  incomingCard: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.primary,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  incomingTitle: { fontFamily: fonts.bold, fontSize: type.base, color: colors.primary },
  incomingMeta: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.text },
  actionRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xs },
  swapReqRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  swapReqTitle: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  swapStatusChip: {
    alignSelf: "flex-start",
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 2,
  },
  swapStatusText: { fontFamily: fonts.semiBold, fontSize: 12, color: "#FFFFFF" },
  cancelBtn: { minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.sm },
  cancelText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.danger },
});
