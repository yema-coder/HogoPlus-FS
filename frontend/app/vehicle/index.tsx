import { useRouter } from "expo-router";
import { LogIn, LogOut, Plus } from "lucide-react-native";
import React, { useCallback, useState } from "react";
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import {
  listVehicleLogs,
  vehiclesInside,
  vehiclesSummary,
  type VehicleLogItem,
} from "@/src/api/endpoints";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { colors, fonts, radius, shadow, sizes, spacing, type } from "@/src/theme/tokens";

const TYPE_EMOJI: Record<string, string> = {
  truck: "🚛",
  tractor: "🚜",
  tempo: "🛻",
  car: "🚗",
  bike: "🏍️",
  bus: "🚌",
  jcb: "🚧",
  bullock_cart: "🐂",
  other: "🚙",
};

function todayIso(): string {
  // gate register day = FACTORY day (IST), independent of device timezone
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export default function VehicleRegisterScreen() {
  const { t } = useTranslation();
  const router = useRouter();
  const [tab, setTab] = useState<"today" | "inside">("today");

  const logs = useCachedFetch("vehicle-logs-today", () => listVehicleLogs({ day: todayIso() }));
  const inside = useCachedFetch("vehicle-inside", vehiclesInside);
  const summary = useCachedFetch("vehicle-summary", vehiclesSummary);

  const refresh = useCallback(() => {
    void logs.refresh();
    void inside.refresh();
    void summary.refresh();
  }, [logs, inside, summary]);

  const data = (tab === "today" ? logs.data : inside.data) ?? [];

  const renderRow = ({ item }: { item: VehicleLogItem }) => {
    const isIn = item.direction === "in";
    const time = new Date(item.logged_at).toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Kolkata",
    });
    return (
      <View style={[styles.row, shadow.card]} testID={`vehicle-row-${item.plate}`}>
        <Text style={styles.rowEmoji}>{TYPE_EMOJI[item.vehicle_type] ?? "🚙"}</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.plate}>{item.plate}</Text>
          <Text style={styles.rowSub} numberOfLines={1}>
            {time}
            {item.gate_zone ? ` · ${item.gate_zone}` : ""}
            {item.purpose ? ` · ${item.purpose}` : ""}
            {typeof item.hours_inside === "number" ? ` · ${item.hours_inside}h` : ""}
          </Text>
        </View>
        <View style={[styles.dirChip, isIn ? styles.dirIn : styles.dirOut]}>
          {isIn ? (
            <LogIn size={16} color="#FFFFFF" strokeWidth={2.6} />
          ) : (
            <LogOut size={16} color="#FFFFFF" strokeWidth={2.6} />
          )}
          <Text style={styles.dirText}>{isIn ? t("veh.in") : t("veh.out")}</Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} testID="vehicle-register-screen">
      <ScreenHeader title={t("veh.registerTitle")} />
      <View style={styles.summaryRow}>
        <View style={styles.summaryCell}>
          <Text style={styles.summaryVal}>{summary.data?.today_in ?? "–"}</Text>
          <Text style={styles.summaryLbl}>{t("veh.todayIn")}</Text>
        </View>
        <View style={styles.summaryCell}>
          <Text style={styles.summaryVal}>{summary.data?.today_out ?? "–"}</Text>
          <Text style={styles.summaryLbl}>{t("veh.todayOut")}</Text>
        </View>
        <View style={styles.summaryCell}>
          <Text style={[styles.summaryVal, { color: colors.warning }]}>
            {summary.data?.currently_inside ?? "–"}
          </Text>
          <Text style={styles.summaryLbl}>{t("veh.inside")}</Text>
        </View>
      </View>
      <View style={styles.tabRow}>
        {(["today", "inside"] as const).map((k) => (
          <Pressable
            key={k}
            testID={`vehicle-tab-${k}`}
            onPress={() => setTab(k)}
            style={[styles.tabBtn, tab === k && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === k && styles.tabTextActive]}>
              {k === "today" ? t("veh.tabToday") : t("veh.tabInside")}
            </Text>
          </Pressable>
        ))}
      </View>
      <FlatList
        data={data}
        keyExtractor={(v) => v.id}
        renderItem={renderRow}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl refreshing={false} onRefresh={refresh} tintColor={colors.primary} />
        }
        ListEmptyComponent={
          <Text style={styles.empty}>
            {logs.loading || inside.loading ? "…" : t("veh.empty")}
          </Text>
        }
      />
      <Pressable
        testID="vehicle-new-fab"
        accessibilityRole="button"
        onPress={() => router.push("/vehicle/new")}
        style={({ pressed }) => [styles.fab, shadow.card, { opacity: pressed ? 0.9 : 1 }]}
      >
        <Plus size={26} color="#FFFFFF" strokeWidth={2.8} />
        <Text style={styles.fabText}>{t("veh.newEntry")}</Text>
      </Pressable>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  summaryRow: {
    flexDirection: "row",
    marginHorizontal: sizes.screenPadding,
    marginTop: spacing.md,
    backgroundColor: "#FFFFFF",
    borderRadius: radius.lg,
    paddingVertical: spacing.md,
  },
  summaryCell: { flex: 1, alignItems: "center", gap: 2 },
  summaryVal: { fontFamily: fonts.bold, fontSize: 26, color: colors.text },
  summaryLbl: { fontFamily: fonts.semiBold, fontSize: type.xs, color: colors.muted },
  tabRow: {
    flexDirection: "row",
    marginHorizontal: sizes.screenPadding,
    marginTop: spacing.md,
    gap: spacing.sm,
  },
  tabBtn: {
    flex: 1,
    minHeight: 44,
    borderRadius: radius.md,
    backgroundColor: "#FFFFFF",
    alignItems: "center",
    justifyContent: "center",
  },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  tabTextActive: { color: "#FFFFFF" },
  list: { padding: sizes.screenPadding, gap: spacing.sm, paddingBottom: 120 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: "#FFFFFF",
    borderRadius: radius.lg,
    padding: spacing.md,
    minHeight: 64,
  },
  rowEmoji: { fontSize: 30 },
  plate: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, letterSpacing: 1 },
  rowSub: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, marginTop: 2 },
  dirChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
  },
  dirIn: { backgroundColor: colors.success },
  dirOut: { backgroundColor: colors.accent },
  dirText: { fontFamily: fonts.bold, fontSize: type.sm, color: "#FFFFFF" },
  empty: {
    textAlign: "center",
    fontFamily: fonts.regular,
    color: colors.muted,
    marginTop: spacing.xxl,
  },
  fab: {
    position: "absolute",
    bottom: spacing.xl,
    alignSelf: "center",
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.primary,
    borderRadius: 32,
    paddingHorizontal: spacing.xl,
    minHeight: 60,
  },
  fabText: { fontFamily: fonts.bold, fontSize: type.lg, color: "#FFFFFF" },
});
