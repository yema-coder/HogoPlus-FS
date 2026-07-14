import dayjs from "dayjs";
import { useRouter } from "expo-router";
import { Send, UserRound } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { createSwap, myShifts, swapCandidates } from "@/src/api/endpoints";
import type { ShiftDay, SwapCandidate } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

export default function NewSwapScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const shifts = useCachedFetch<ShiftDay[]>("shifts", myShifts);

  const [date, setDate] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<SwapCandidate[] | null>(null);
  const [loadingCands, setLoadingCands] = useState(false);
  const [target, setTarget] = useState<SwapCandidate | null>(null);
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);

  // next 7 days (skip today)
  const days = (shifts.data ?? []).slice(1, 8);

  useEffect(() => {
    if (!date) return;
    let active = true;
    setLoadingCands(true);
    setCandidates(null);
    setTarget(null);
    void swapCandidates(date)
      .then((res) => {
        if (active) setCandidates(res.candidates);
      })
      .catch(() => {
        if (active) setCandidates([]);
      })
      .finally(() => {
        if (active) setLoadingCands(false);
      });
    return () => {
      active = false;
    };
  }, [date]);

  const send = async () => {
    if (!date || !target || sending) return;
    setSending(true);
    try {
      await createSwap({
        target_employee_id: target.employee_id,
        swap_date: date,
        reason: reason.trim() || null,
      });
      showToast(t("swap.sent"), "success");
      router.back();
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else if (e instanceof ApiError && typeof e.detail === "string") showToast(e.detail, "error");
      else showToast(t("errors.server"), "error");
      setSending(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="new-swap-screen">
      <ScreenHeader title={t("swap.title")} />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.sectionTitle}>{t("swap.pickDate")}</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.dayRow}>
          {days.map((d) => {
            const active = date === d.date;
            const hasShift = Boolean(d.shift_code);
            return (
              <Pressable
                key={d.date}
                testID={`swap-date-${d.date}`}
                disabled={!hasShift}
                onPress={() => setDate(d.date)}
                style={[styles.dayChip, active && styles.dayChipActive, !hasShift && { opacity: 0.4 }]}
              >
                <Text style={[styles.dayChipDay, active && styles.dayChipTextActive]}>
                  {t(`week.d${dayjs(d.date).day()}`)}
                </Text>
                <Text style={[styles.dayChipDate, active && styles.dayChipTextActive]}>
                  {dayjs(d.date).format("DD/MM")}
                </Text>
                <View style={[styles.dayShift, active && styles.dayShiftActive]}>
                  <Text style={[styles.dayShiftText, active && { color: colors.onPrimary }]}>
                    {d.shift_code ?? "—"}
                  </Text>
                </View>
              </Pressable>
            );
          })}
        </ScrollView>

        {date ? (
          <>
            <Text style={styles.sectionTitle}>{t("swap.pickColleague")}</Text>
            {loadingCands ? (
              <ActivityIndicator size="large" color={colors.primary} style={{ marginVertical: spacing.lg }} />
            ) : (candidates ?? []).length === 0 ? (
              <View style={styles.emptyCard} testID="no-candidates">
                <Text style={styles.emptyText}>{t("swap.noCandidates")}</Text>
              </View>
            ) : (
              <View style={{ gap: spacing.sm }}>
                {(candidates ?? []).map((c) => {
                  const active = target?.employee_id === c.employee_id;
                  return (
                    <Pressable
                      key={c.employee_id}
                      testID={`swap-candidate-${c.emp_id}`}
                      onPress={() => setTarget(c)}
                      style={[styles.candRow, active && styles.candRowActive]}
                    >
                      <View style={styles.candAvatar}>
                        <UserRound size={24} color={active ? colors.primary : colors.muted} strokeWidth={2.2} />
                      </View>
                      <View style={{ flex: 1, gap: 2 }}>
                        <Text style={[styles.candName, active && { color: colors.primary }]} numberOfLines={1}>
                          {c.full_name}
                        </Text>
                        <Text style={styles.candMeta}>{c.emp_id}</Text>
                      </View>
                      <View style={styles.candShift}>
                        <Text style={styles.candShiftText}>{c.shift_code}</Text>
                      </View>
                    </Pressable>
                  );
                })}
              </View>
            )}
          </>
        ) : null}

        {target ? (
          <>
            <Text style={styles.youGet}>
              {t("swap.youGet")}: {t("att.shift")} {target.shift_code}
            </Text>
            <Text style={styles.sectionTitle}>{t("swap.reasonOptional")}</Text>
            <TextInput
              testID="swap-reason-input"
              style={styles.reasonInput}
              value={reason}
              onChangeText={setReason}
              placeholder={t("swap.reasonOptional")}
              placeholderTextColor={colors.muted}
              maxLength={200}
            />
            <BigButton
              testID="swap-send-button"
              label={t("swap.send")}
              icon={Send}
              height={64}
              loading={sending}
              onPress={() => void send()}
              style={{ marginTop: spacing.md }}
            />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.xxl },
  sectionTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  dayRow: { gap: spacing.sm },
  dayChip: {
    width: 84,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    paddingVertical: spacing.md,
    gap: 4,
  },
  dayChipActive: { borderColor: colors.primary, backgroundColor: colors.brandTertiary },
  dayChipDay: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  dayChipDate: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  dayChipTextActive: { color: colors.primary },
  dayShift: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  dayShiftActive: { backgroundColor: colors.primary },
  dayShiftText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  emptyCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.xl,
    alignItems: "center",
  },
  emptyText: { fontFamily: fonts.medium, fontSize: type.base, color: colors.muted, textAlign: "center" },
  candRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    padding: spacing.lg,
    minHeight: 72,
  },
  candRowActive: { borderColor: colors.primary, backgroundColor: colors.brandTertiary },
  candAvatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  candName: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  candMeta: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  candShift: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  candShiftText: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.primary },
  youGet: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.success },
  reasonInput: {
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
  },
});
