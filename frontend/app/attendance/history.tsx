import dayjs from "dayjs";
import { CalendarX2, ChevronLeft, ChevronRight } from "lucide-react-native";
import React, { useState } from "react";
import { FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { uploadFile } from "@/src/api/client";
import {
  attendanceMonthSummary,
  myAttendance,
  regularizeAttendance,
  type MonthSummaryCounts,
} from "@/src/api/endpoints";
import type { AttendanceRecord } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { VoiceFieldInput } from "@/src/forms/fields/VoiceFieldInput";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatTime } from "@/src/utils/format";

const LEVEL_COLORS: Record<string, string> = {
  verified_plus: colors.success,
  verified: colors.success,
  flagged: colors.warning,
};

export default function AttendanceHistory() {
  const { t } = useTranslation();
  const [month, setMonth] = useState(dayjs().startOf("month"));
  const key = month.format("YYYY-MM");
  const { data, loading, error, refresh } = useCachedFetch<AttendanceRecord[]>(
    `att-${key}`,
    () => myAttendance(key),
  );
  // v1.0.21 "My Month" — same numbers the Time Office sees (shared endpoint)
  const summary = useCachedFetch<{ current: MonthSummaryCounts; previous: MonthSummaryCounts }>(
    `att-sum-${key}`,
    () => attendanceMonthSummary(key),
  );

  // v1.0.21 regularization: one-tap "this is wrong" on flagged punches
  const [disputeTarget, setDisputeTarget] = useState<AttendanceRecord | null>(null);
  const [disputeText, setDisputeText] = useState("");
  const [disputeVoice, setDisputeVoice] = useState<string | undefined>(undefined);
  const [sending, setSending] = useState(false);

  const sendDispute = async () => {
    if (!disputeTarget || sending) return;
    setSending(true);
    try {
      let voiceKey: string | null = null;
      if (disputeVoice) {
        const up = await uploadFile(disputeVoice, "voice_note.m4a").catch(() => null);
        voiceKey = up?.key ?? null;
      }
      await regularizeAttendance(disputeTarget.id, {
        text_note: disputeText.trim() || null,
        voice_note_key: voiceKey,
      });
      showToast(t("att.disputeSent"), "success");
      setDisputeTarget(null);
      setDisputeText("");
      setDisputeVoice(undefined);
      void refresh();
      void summary.refresh();
    } catch {
      showToast(t("common.error"), "error");
    } finally {
      setSending(false);
    }
  };

  const isCurrent = key === dayjs().format("YYYY-MM");

  const levelLabel = (level: string) =>
    level === "verified_plus"
      ? t("att.verifiedPlus")
      : level === "verified"
        ? t("att.verified")
        : t("att.flagged");

  const renderRow = ({ item }: { item: AttendanceRecord }) => {
    const d = dayjs(item.date);
    return (
      <View style={styles.row} testID={`attendance-row-${item.date}`}>
        <View style={styles.dateBox}>
          <Text style={styles.dateNum}>{d.format("DD")}</Text>
          <Text style={styles.dateDay}>{t(`week.d${d.day()}`)}</Text>
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={styles.times}>
            {t("att.punchedInAt")} {formatTime(item.punch_in_at)}
            {item.punch_out_at ? ` · ${t("att.punchedOutAt")} ${formatTime(item.punch_out_at)}` : ""}
          </Text>
          <View style={styles.chipRow}>
            <View style={[styles.chip, { backgroundColor: LEVEL_COLORS[item.verification_level] ?? colors.muted }]}>
              <Text style={styles.chipText}>{levelLabel(item.verification_level)}</Text>
            </View>
            {item.is_late ? (
              <View style={[styles.chip, { backgroundColor: colors.warning }]}>
                <Text style={[styles.chipText, { color: colors.onWarning }]}>{t("att.late")}</Text>
              </View>
            ) : null}
            {item.shift_code ? (
              <View style={[styles.chip, { backgroundColor: colors.brandTertiary }]}>
                <Text style={[styles.chipText, { color: colors.primary }]}>
                  {t("att.shift")} {item.shift_code}
                </Text>
              </View>
            ) : null}
          </View>
          {item.regularization ? (
            <View
              style={[
                styles.regStatus,
                item.regularization.status === "approved" && { backgroundColor: `${colors.success}18` },
                item.regularization.status === "rejected" && { backgroundColor: `${colors.danger}18` },
              ]}
              testID={`reg-status-${item.date}`}
            >
              <Text
                style={[
                  styles.regStatusText,
                  item.regularization.status === "approved" && { color: colors.success },
                  item.regularization.status === "rejected" && { color: colors.danger },
                ]}
              >
                {t(`att.reg_${item.regularization.status}`)}
              </Text>
            </View>
          ) : item.verification_level === "flagged" && !item.approved_by ? (
            <Pressable
              testID={`dispute-button-${item.date}`}
              accessibilityRole="button"
              onPress={() => setDisputeTarget(item)}
              style={({ pressed }) => [styles.disputeBtn, { opacity: pressed ? 0.8 : 1 }]}
            >
              <Text style={styles.disputeBtnText}>✋ {t("att.thisIsWrong")}</Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="attendance-history-screen">
      <ScreenHeader title={t("att.title")} />
      <View style={styles.monthRow}>
        <Pressable
          testID="month-prev-button"
          onPress={() => setMonth((m) => m.subtract(1, "month"))}
          style={styles.monthBtn}
        >
          <ChevronLeft size={26} color={colors.text} strokeWidth={2.4} />
        </Pressable>
        <Text style={styles.monthLabel}>{month.format("MM/YYYY")}</Text>
        <Pressable
          testID="month-next-button"
          onPress={() => {
            if (!isCurrent) setMonth((m) => m.add(1, "month"));
          }}
          style={[styles.monthBtn, isCurrent && { opacity: 0.3 }]}
        >
          <ChevronRight size={26} color={colors.text} strokeWidth={2.4} />
        </Pressable>
      </View>
      {error && !data ? (
        <ErrorRetry onRetry={() => void refresh()} />
      ) : (
        <FlatList
          data={data ?? []}
          keyExtractor={(r) => r.id}
          renderItem={renderRow}
          contentContainerStyle={styles.list}
          refreshing={loading}
          onRefresh={() => void refresh()}
          ListHeaderComponent={
            summary.data ? (
              <View style={styles.summaryCard} testID="my-month-card">
                <Text style={styles.summaryTitle}>📅 {t("att.myMonth")}</Text>
                <View style={styles.summaryRow}>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryNum}>{summary.data.current.days_present}</Text>
                    <Text style={styles.summaryLabel}>{t("att.daysPresent")}</Text>
                  </View>
                  <View style={styles.summaryCell}>
                    <Text style={[styles.summaryNum, summary.data.current.days_flagged_pending > 0 && { color: colors.warning }]}>
                      {summary.data.current.days_flagged_pending}
                    </Text>
                    <Text style={styles.summaryLabel}>{t("att.flagged")}</Text>
                  </View>
                  <View style={styles.summaryCell}>
                    <Text style={styles.summaryNum}>{summary.data.current.days_late}</Text>
                    <Text style={styles.summaryLabel}>{t("att.lateDays")}</Text>
                  </View>
                </View>
                <Text style={styles.summaryPrev}>
                  {t("att.prevMonth", { n: summary.data.previous.days_present })}
                </Text>
              </View>
            ) : null
          }
          ListEmptyComponent={<EmptyState icon={CalendarX2} title={t("att.noRecords")} />}
        />
      )}
      <Modal
        visible={disputeTarget !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setDisputeTarget(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard} testID="dispute-modal">
            <Text style={styles.modalTitle}>✋ {t("att.disputeTitle")}</Text>
            {disputeTarget ? (
              <Text style={styles.modalMeta}>
                {dayjs(disputeTarget.date).format("DD/MM/YYYY")} ·{" "}
                {formatTime(disputeTarget.punch_in_at)}
              </Text>
            ) : null}
            <VoiceFieldInput value={disputeVoice} onChange={setDisputeVoice} testID="dispute-voice" />
            <TextInput
              testID="dispute-text-input"
              style={styles.modalInput}
              value={disputeText}
              onChangeText={setDisputeText}
              placeholder={t("att.disputeHint")}
              placeholderTextColor={colors.muted}
              multiline
              maxLength={500}
            />
            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <BigButton
                  testID="dispute-cancel"
                  label={t("common.cancel")}
                  variant="outline"
                  onPress={() => setDisputeTarget(null)}
                />
              </View>
              <View style={{ flex: 1 }}>
                <BigButton
                  testID="dispute-send"
                  label={t("common.submit")}
                  loading={sending}
                  onPress={() => void sendDispute()}
                />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  monthRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: sizes.screenPadding,
    paddingTop: spacing.md,
  },
  monthBtn: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  monthLabel: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
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
  },
  dateBox: {
    width: 56,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.sm,
    paddingVertical: spacing.sm,
  },
  dateNum: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.primary },
  dateDay: { fontFamily: fonts.medium, fontSize: 12, color: colors.primary },
  times: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  chipRow: { flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" },
  chip: {
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 2,
  },
  chipText: { fontFamily: fonts.semiBold, fontSize: 12, color: "#FFFFFF" },
  summaryCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  summaryTitle: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  summaryRow: { flexDirection: "row", gap: spacing.md },
  summaryCell: {
    flex: 1,
    alignItems: "center",
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.sm,
    paddingVertical: spacing.md,
    gap: 2,
  },
  summaryNum: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.primary },
  summaryLabel: { fontFamily: fonts.medium, fontSize: 12, color: colors.text, textAlign: "center" },
  summaryPrev: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  regStatus: {
    alignSelf: "flex-start",
    backgroundColor: `${colors.warning}18`,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 3,
    marginTop: spacing.xs,
  },
  regStatusText: { fontFamily: fonts.bold, fontSize: 12, color: colors.warning },
  disputeBtn: {
    alignSelf: "flex-start",
    borderWidth: 1.5,
    borderColor: colors.warning,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    marginTop: spacing.xs,
    minHeight: 32,
    justifyContent: "center",
  },
  disputeBtnText: { fontFamily: fonts.bold, fontSize: 13, color: colors.warning },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "center",
    padding: sizes.screenPadding,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.md,
  },
  modalTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  modalMeta: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  modalInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    minHeight: 72,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    textAlignVertical: "top",
  },
});
