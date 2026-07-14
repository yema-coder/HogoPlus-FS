import dayjs from "dayjs";
import { CalendarX2 } from "lucide-react-native";
import React from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { myShifts } from "@/src/api/endpoints";
import type { ShiftDay } from "@/src/api/types";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatShiftTime } from "@/src/utils/format";

export default function ShiftScreen() {
  const { t } = useTranslation();
  const { data, loading, error, refresh } = useCachedFetch<ShiftDay[]>("shifts", myShifts);

  const dayLabel = (dateStr: string, index: number): string => {
    if (index === 0) return t("common.today");
    if (index === 1) return t("common.tomorrow");
    const d = dayjs(dateStr);
    return `${t(`week.d${d.day()}`)} ${d.format("DD/MM")}`;
  };

  const renderRow = ({ item, index }: { item: ShiftDay; index: number }) => (
    <View style={[styles.row, index === 0 && styles.rowToday]} testID={`shift-row-${item.date}`}>
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
  );

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="shift-screen">
      <ScreenHeader title={t("shift.title")} />
      {error && !data ? (
        <ErrorRetry onRetry={() => void refresh()} />
      ) : (
        <FlatList
          data={data ?? []}
          keyExtractor={(s) => s.date}
          renderItem={renderRow}
          contentContainerStyle={styles.list}
          refreshing={loading}
          onRefresh={() => void refresh()}
          ListEmptyComponent={<EmptyState icon={CalendarX2} title={t("shift.noShift")} />}
        />
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
});
