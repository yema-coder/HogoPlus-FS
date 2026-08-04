import { useFocusEffect, useRouter } from "expo-router";
import { ClipboardList, CloudOff, Unlink } from "lucide-react-native";
import React, { useCallback, useMemo, useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { listIncidents, myIncidents, unlinkDuplicate } from "@/src/api/endpoints";
import type { Incident } from "@/src/api/types";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { EyeLoader } from "@/src/components/EyeLoader";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { SkeletonRows } from "@/src/components/Skeleton";
import { StatusChip } from "@/src/components/StatusChip";
import { showToast } from "@/src/components/Toast";
import { UpdatedNote } from "@/src/components/UpdatedNote";
import { categoryDef } from "@/src/constants/categories";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatDateTime, formatTime, timeAgo } from "@/src/utils/format";

type Scope = "mine" | "dept";
type GroupedIncident = Incident & { children: Incident[] };

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
  const uploadingId = useOutboxStore((s) => s.uploadingId);
  const [unlinking, setUnlinking] = useState(false);

  // v1.0.21 duplicate clustering: in the DEPT view, incidents linked to a root
  // collapse under the root's card ("2 reports: 10:14, 10:31"). DISPLAY-ONLY —
  // each record keeps its own reporter, status and detail screen.
  const grouped: GroupedIncident[] = useMemo(() => {
    const items = data ?? [];
    if (scope !== "dept") return items.map((i) => ({ ...i, children: [] }));
    const byId = new Map(items.map((i) => [i.id, i]));
    const childrenOf = new Map<string, Incident[]>();
    const roots: Incident[] = [];
    for (const i of items) {
      if (i.duplicate_of && byId.has(i.duplicate_of)) {
        const arr = childrenOf.get(i.duplicate_of) ?? [];
        arr.push(i);
        childrenOf.set(i.duplicate_of, arr);
      } else {
        roots.push(i); // root, or orphan child whose root isn't in this page
      }
    }
    return roots.map((r) => ({
      ...r,
      children: (childrenOf.get(r.id) ?? []).sort((a, b) =>
        (a.created_at ?? "").localeCompare(b.created_at ?? ""),
      ),
    }));
  }, [data, scope]);

  const doUnlink = async (child: Incident) => {
    if (unlinking) return;
    setUnlinking(true);
    try {
      await unlinkDuplicate(child.id);
      showToast(t("dup.unlinked"), "success");
      void refresh();
    } catch {
      showToast(t("errors.server"), "error");
    } finally {
      setUnlinking(false);
    }
  };

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const renderRow = ({ item }: { item: GroupedIncident }) => {
    const def = categoryDef(item.category);
    const Icon = def.icon;
    const all = [item, ...item.children];
    return (
      <View>
        <Pressable
          testID={`incident-row-${item.id}`}
          accessibilityRole="button"
          onPress={() => router.push({ pathname: "/incident/[id]", params: { id: item.id } })}
          style={({ pressed }) => [
            styles.row,
            item.children.length > 0 && styles.rowClustered,
            { opacity: pressed ? 0.85 : 1 },
          ]}
        >
          <View style={[styles.iconWrap, { backgroundColor: `${def.tint}18` }]}>
            <Icon size={26} color={def.tint} strokeWidth={2.2} />
          </View>
          <View style={styles.rowBody}>
            <Text style={styles.rowTitle} numberOfLines={1}>
              {t(def.tKey)}
            </Text>
            <Text style={styles.rowSub} numberOfLines={1}>
              {timeAgo(item.created_at)}
            </Text>
            {item.children.length > 0 ? (
              <Text style={styles.dupBadge} testID={`dup-badge-${item.id}`}>
                🔁 {t("dup.reports", { count: all.length })}:{" "}
                {all.map((i) => formatTime(i.created_at)).join(", ")}
              </Text>
            ) : null}
          </View>
          <StatusChip status={item.status} />
        </Pressable>
        {item.children.map((c) => (
          <View key={c.id} style={styles.childRow} testID={`dup-child-${c.id}`}>
            <Pressable
              accessibilityRole="button"
              onPress={() => router.push({ pathname: "/incident/[id]", params: { id: c.id } })}
              style={({ pressed }) => [styles.childBody, { opacity: pressed ? 0.8 : 1 }]}
            >
              <Text style={styles.childText} numberOfLines={1}>
                {c.reporter_name ?? ""} · {formatTime(c.created_at)}
              </Text>
            </Pressable>
            <Pressable
              testID={`dup-unlink-${c.id}`}
              accessibilityRole="button"
              accessibilityLabel={t("dup.unlink")}
              onPress={() => void doUnlink(c)}
              hitSlop={8}
              style={({ pressed }) => [styles.unlinkBtn, { opacity: pressed ? 0.7 : 1 }]}
            >
              <Unlink size={16} color={colors.danger} strokeWidth={2.4} />
            </Pressable>
          </View>
        ))}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="reports-screen">
      <ScreenHeader title={t("reports.title")} backTo="/(tabs)/home" />

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
          data={grouped}
          keyExtractor={(i) => i.id}
          renderItem={renderRow}
          contentContainerStyle={styles.list}
          refreshing={loading}
          onRefresh={() => void refresh()}
          ListHeaderComponent={
            <>
              {loading && data ? (
                <View style={styles.refreshStrip} testID="reports-refresh-strip">
                  <EyeLoader size={18} />
                </View>
              ) : null}
              {outboxIncidents.length > 0 && scope === "mine" ? (
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
                      {uploadingId === item.id ? (
                        <View
                          style={[styles.queuedChip, { backgroundColor: colors.accent }]}
                          testID={`outbox-chip-uploading-${item.id}`}
                        >
                          <EyeLoader size={12} />
                          <Text style={[styles.queuedText, { color: "#FFFFFF" }]}>
                            {t("status.uploading")}
                          </Text>
                        </View>
                      ) : (
                        <View style={styles.queuedChip} testID={`outbox-chip-${item.id}`}>
                          <CloudOff size={14} color={colors.onWarning} strokeWidth={2.4} />
                          <Text style={styles.queuedText}>
                            {t(item.retries > 0 ? "status.willRetry" : "status.queued")}
                          </Text>
                        </View>
                      )}
                    </View>
                  );
                })}
              </View>
            ) : null}
            </>
          }
          ListEmptyComponent={
            loading && !data ? (
              <SkeletonRows rows={6} />
            ) : outboxIncidents.length === 0 || scope === "dept" ? (
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
  refreshStrip: { alignItems: "center", paddingBottom: spacing.md },
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
  rowClustered: { borderColor: colors.primary, borderWidth: 1.5 },
  dupBadge: { fontFamily: fonts.bold, fontSize: 12, color: colors.primary },
  childRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginLeft: spacing.xl,
    marginTop: spacing.xs,
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 44,
  },
  childBody: { flex: 1, justifyContent: "center" },
  childText: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.text },
  unlinkBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: `${colors.danger}12`,
  },
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
