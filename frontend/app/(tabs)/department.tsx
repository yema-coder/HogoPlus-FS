import { useFocusEffect, useRouter } from "expo-router";
import { ClipboardList, FileText } from "lucide-react-native";
import React, { useCallback, useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { listForms, listSubmissions } from "@/src/api/endpoints";
import type { FormDefinitionItem, SubmissionList } from "@/src/api/types";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { StatusChip } from "@/src/components/StatusChip";
import { departmentIcon } from "@/src/constants/departments";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatDateTime } from "@/src/utils/format";

type SubScope = "mine" | "dept";

export default function DepartmentScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const rank = profile?.role?.rank ?? 6;
  const isStaffClerk = rank === 4 || rank === 5;
  const dept = profile?.department_code ?? "";
  const [scope, setScope] = useState<SubScope>("mine");

  const forms = useCachedFetch<FormDefinitionItem[]>(`forms-${dept}`, () => listForms());
  const subsKey = scope === "mine" ? "subs-mine" : "subs-dept";
  const subs = useCachedFetch<SubmissionList>(subsKey, () =>
    listSubmissions(scope === "dept" ? { scope: "department" } : {}),
  );

  useFocusEffect(
    useCallback(() => {
      void forms.refresh();
      void subs.refresh();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [subsKey]),
  );

  // managers get dept-wide lists from the default endpoint; "mine" filters client-side
  const subItems = (subs.data?.items ?? []).filter((s) =>
    scope === "mine" ? s.submitted_by === profile?.id : true,
  );

  const DeptIcon = departmentIcon(dept);

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="department-screen">
      <ScreenHeader
        title={
          profile?.department
            ? tri(profile.department as unknown as Record<string, unknown>, "name")
            : t("tabs.dept")
        }
        back={false}
      />
      <FlatList
        data={subItems}
        keyExtractor={(s) => s.id}
        contentContainerStyle={styles.list}
        refreshing={subs.loading}
        onRefresh={() => {
          void forms.refresh();
          void subs.refresh();
        }}
        ListHeaderComponent={
          <View style={styles.headerWrap}>
            <Text style={styles.sectionTitle}>{t("forms.title")}</Text>
            {forms.error && !forms.data ? (
              <ErrorRetry onRetry={() => void forms.refresh()} />
            ) : (forms.data ?? []).length === 0 ? (
              <View style={styles.noFormsCard}>
                <DeptIcon size={28} color={colors.muted} strokeWidth={2} />
                <Text style={styles.noFormsText}>{t("forms.noForms")}</Text>
              </View>
            ) : (
              <View style={styles.tileGrid}>
                {(forms.data ?? []).map((f) => (
                  <Pressable
                    key={f.id}
                    testID={`form-tile-${f.code}`}
                    accessibilityRole="button"
                    onPress={() => router.push(`/form/${f.id}`)}
                    style={({ pressed }) => [styles.formTile, { opacity: pressed ? 0.85 : 1 }]}
                  >
                    <View style={styles.formIconWrap}>
                      <FileText size={30} color={colors.primary} strokeWidth={2.2} />
                    </View>
                    <Text style={styles.formTitle} numberOfLines={2}>
                      {tri(f as unknown as Record<string, unknown>, "title")}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}

            <View style={styles.subsHead}>
              <Text style={styles.sectionTitle}>
                {scope === "mine" ? t("forms.mySubs") : t("forms.deptSubs")}
              </Text>
            </View>
            {isStaffClerk ? (
              <View style={styles.toggleRow}>
                {(["mine", "dept"] as SubScope[]).map((s) => (
                  <Pressable
                    key={s}
                    testID={`subs-scope-${s}`}
                    onPress={() => setScope(s)}
                    style={[styles.toggle, scope === s && styles.toggleActive]}
                  >
                    <Text style={[styles.toggleText, scope === s && styles.toggleTextActive]}>
                      {t(s === "mine" ? "forms.mySubs" : "forms.deptSubs")}
                    </Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
          </View>
        }
        renderItem={({ item }) => (
          <Pressable
            testID={`submission-row-${item.id}`}
            accessibilityRole="button"
            onPress={() => router.push(`/submission/${item.id}`)}
            style={({ pressed }) => [styles.subRow, { opacity: pressed ? 0.85 : 1 }]}
          >
            <View style={styles.subIconWrap}>
              <ClipboardList size={24} color={colors.accent} strokeWidth={2.2} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.subTitle} numberOfLines={1}>
                {tri(item as unknown as Record<string, unknown>, "form_title") || item.form_code || t("forms.title")}
              </Text>
              <Text style={styles.subMeta} numberOfLines={1}>
                {scope === "dept" && item.submitted_by_name
                  ? `${item.submitted_by_name} · ${formatDateTime(item.created_at)}`
                  : formatDateTime(item.created_at)}
              </Text>
            </View>
            <StatusChip status={item.status} />
          </Pressable>
        )}
        ListEmptyComponent={
          subs.error && !subs.data ? (
            <ErrorRetry onRetry={() => void subs.refresh()} />
          ) : (
            <EmptyState icon={ClipboardList} title={t("forms.noSubs")} />
          )
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  list: { padding: sizes.screenPadding, gap: spacing.md, flexGrow: 1 },
  headerWrap: { gap: spacing.md, marginBottom: spacing.sm },
  sectionTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  noFormsCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  noFormsText: { fontFamily: fonts.medium, fontSize: type.base, color: colors.muted },
  tileGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  formTile: {
    flexBasis: "47%",
    flexGrow: 1,
    minHeight: 120,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
    justifyContent: "center",
  },
  formIconWrap: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  formTitle: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  subsHead: { marginTop: spacing.md },
  toggleRow: { flexDirection: "row", gap: spacing.sm },
  toggle: {
    flex: 1,
    height: 48,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.sm,
  },
  toggleActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  toggleText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  toggleTextActive: { color: colors.onPrimary },
  subRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    minHeight: 72,
  },
  subIconWrap: {
    width: 44,
    height: 44,
    borderRadius: radius.sm,
    backgroundColor: `${colors.accent}18`,
    alignItems: "center",
    justifyContent: "center",
  },
  subTitle: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  subMeta: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
});
