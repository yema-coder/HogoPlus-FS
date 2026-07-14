import dayjs from "dayjs";
import { CalendarX2, ChevronLeft, ChevronRight } from "lucide-react-native";
import React, { useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { myAttendance } from "@/src/api/endpoints";
import type { AttendanceRecord } from "@/src/api/types";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
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
          ListEmptyComponent={<EmptyState icon={CalendarX2} title={t("att.noRecords")} />}
        />
      )}
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
});
