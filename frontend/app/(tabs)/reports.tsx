import { useFocusEffect, useRouter } from "expo-router";
import { ClipboardList, CloudOff } from "lucide-react-native";
import React, { useCallback, useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { listIncidents, myIncidents } from "@/src/api/endpoints";
import type { Incident } from "@/src/api/types";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { StatusChip } from "@/src/components/StatusChip";
import { UpdatedNote } from "@/src/components/UpdatedNote";
import { categoryDef } from "@/src/constants/categories";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatDateTime } from "@/src/utils/format";

type Scope = "mine" | "dept";

export default function ReportsScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const rank = profile?.role?.rank ?? 6;
  const isManager = rank <= 3;
  const [scope, setScope] = useState<Scope>("mine");

  const key = scope === "mine" ? "incidents-mine" : "incidents-dept";
  const fetcher = scope === "mine" ? myIncidents : () => listIncidents();
  const { data, fetchedAt, loading, error, refresh } = useCachedFetch<Incident[]>(key, fetcher);

  const outboxIncidents = useOutboxStore((s) => s.items).filter((i) => i.type === "incident");

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const renderRow = ({ item }: { item: Incident }) => {
    const def = categoryDef(item.category);
    const Icon = def.icon;
    return (
      <Pressable
        testID={`incident-row-${item.id}`}
        accessibilityRole="button"
        onPress={() => router.push(`/incident/${item.id}`)}
        style={({ pressed }) => [styles.row, { opacity: pressed ? 0.85 : 1 }]}
      >
        <View style={[styles.iconWrap, { backgroundColor: `${def.tint}18` }]}>
          <Icon size={26} color={def.tint} strokeWidth={2.2} />
        </View>
        <View style={styles.rowBody}>
          <Text style={styles.rowTitle} numberOfLines={1}>
            {t(def.tKey)}
          </Text>
          <Text style={styles.rowSub} numberOfLines={1}>
            {formatDateTime(item.created_at)}
          </Text>
        </View>
        <StatusChip status={item.status} />
      </Pressable>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="reports-screen">
      <ScreenHeader title={t("reports.title")} back={false} />

      {isManager ? (
        <View style={styles.toggleRow}>
          {(["mine", "dept"] as Scope[]).map((s) => (
            <Pressable
              key={s}
              testID={`reports-scope-${s}`}
              onPress={() => setScope(s)}
              style={[styles.toggle, scope === s && styles.toggleActive]}
            >
              <Text style={[styles.toggleText, scope === s && styles.toggleTextActive]}>
                {t(s === "mine" ? "reports.mineTab" : "reports.deptTab")}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {error && !data ? (
        <ErrorRetry onRetry={() => void refresh()} />
      ) : (
        <FlatList
          data={data ?? []}
          keyExtractor={(i) => i.id}
          renderItem={renderRow}
          contentContainerStyle={styles.list}
          refreshing={loading}
          onRefresh={() => void refresh()}
          ListHeaderComponent={
            outboxIncidents.length > 0 && scope === "mine" ? (
              <View style={styles.outboxWrap} testID="outbox-section">
                <Text style={styles.outboxTitle}>
                  {t("reports.outbox", { count: outboxIncidents.length })}
                </Text>
                {outboxIncidents.map((item) => {
                  const def = categoryDef(String(item.payload.category ?? "other"));
                  const Icon = def.icon;
                  return (
                    <View key={item.id} style={styles.row} testID={`outbox-row-${item.id}`}>
                      <View style={[styles.iconWrap, { backgroundColor: `${colors.warning}18` }]}>
                        <Icon size={26} color={colors.warning} strokeWidth={2.2} />
                      </View>
                      <View style={styles.rowBody}>
                        <Text style={styles.rowTitle}>{t(def.tKey)}</Text>
                        <Text style={styles.rowSub}>{formatDateTime(item.createdAt)}</Text>
                      </View>
                      <View style={styles.queuedChip}>
                        <CloudOff size={14} color={colors.onWarning} strokeWidth={2.4} />
                        <Text style={styles.queuedText}>{t("status.queued")}</Text>
                      </View>
                    </View>
                  );
                })}
              </View>
            ) : null
          }
          ListEmptyComponent={
            outboxIncidents.length === 0 || scope === "dept" ? (
              <EmptyState icon={ClipboardList} title={t("reports.empty")} />
            ) : null
          }
          ListFooterComponent={<UpdatedNote fetchedAt={fetchedAt} />}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  toggleRow: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: sizes.screenPadding,
    paddingTop: spacing.md,
  },
  toggle: {
    flex: 1,
    height: 48,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
  },
  toggleActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  toggleText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  toggleTextActive: { color: colors.onPrimary },
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
  iconWrap: {
    width: 48,
    height: 48,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  rowBody: { flex: 1, gap: 2 },
  rowTitle: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  rowSub: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  outboxWrap: { gap: spacing.md, marginBottom: spacing.md },
  outboxTitle: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.warning },
  queuedChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.warning,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  queuedText: { fontFamily: fonts.semiBold, fontSize: 12, color: colors.onWarning },
});
