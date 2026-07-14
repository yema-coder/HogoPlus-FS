import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { listDepartments } from "@/src/api/endpoints";
import type { DepartmentItem } from "@/src/api/types";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { departmentIcon } from "@/src/constants/departments";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

export default function RegisterDepartment() {
  const router = useRouter();
  const { t } = useTranslation();
  const { name } = useLocalSearchParams<{ name: string }>();
  const { data, loading, error, refresh } = useCachedFetch<DepartmentItem[]>(
    "departments",
    listDepartments,
  );

  const renderItem = ({ item }: { item: DepartmentItem }) => {
    const Icon = departmentIcon(item.code);
    return (
      <Pressable
        testID={`department-card-${item.code}`}
        accessibilityRole="button"
        onPress={() =>
          router.push({
            pathname: "/(auth)/register-selfie",
            params: { name: name ?? "", dept: item.code },
          })
        }
        style={({ pressed }) => [styles.card, { opacity: pressed ? 0.85 : 1 }]}
      >
        <View style={styles.iconWrap}>
          <Icon size={30} color={colors.primary} strokeWidth={2.2} />
        </View>
        <Text style={styles.cardLabel} numberOfLines={2}>
          {tri(item as unknown as Record<string, unknown>, "name")}
        </Text>
      </Pressable>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="register-department-screen">
      <ScreenHeader title={t("reg.deptTitle")} />
      {error && !data ? (
        <ErrorRetry onRetry={() => void refresh()} />
      ) : (
        <FlatList
          data={data ?? []}
          keyExtractor={(d) => d.code}
          renderItem={renderItem}
          numColumns={2}
          columnWrapperStyle={{ gap: spacing.md }}
          contentContainerStyle={styles.list}
          refreshing={loading}
          onRefresh={() => void refresh()}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  list: { padding: sizes.screenPadding, gap: spacing.md },
  card: {
    flex: 1,
    minHeight: 110,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    justifyContent: "center",
  },
  iconWrap: {
    width: 44,
    height: 44,
    borderRadius: radius.sm,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  cardLabel: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
});
