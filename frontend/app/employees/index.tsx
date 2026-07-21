import { useRouter } from "expo-router";
import { ChevronRight, Search, UserPlus } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { searchEmployees } from "@/src/api/endpoints";
import type { EmployeeProfile } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { EyeLoader } from "@/src/components/EyeLoader";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/** Prompt 17 Part B: employee directory for Time Office Manager / CGM / MD —
 * search, tap-to-edit, and direct-add. Backend enforces all guardrails. */
export default function EmployeesScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<EmployeeProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setSearched(false);
      return;
    }
    const timer = setTimeout(() => {
      setLoading(true);
      searchEmployees(q)
        .then((rows) => {
          setResults(rows);
          setSearched(true);
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 400);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="employees-screen">
      <ScreenHeader title={t("emp.title")} />
      <View style={styles.content}>
        <View style={styles.searchRow}>
          <Search size={20} color={colors.muted} strokeWidth={2.2} />
          <TextInput
            testID="employee-search-input"
            style={styles.searchInput}
            value={query}
            onChangeText={setQuery}
            placeholder={t("emp.search")}
            placeholderTextColor={colors.muted}
            autoCorrect={false}
          />
          {loading ? <EyeLoader size={18} /> : null}
        </View>

        <FlatList
          data={results}
          keyExtractor={(item) => item.id}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingBottom: spacing.xl }}
          ListEmptyComponent={
            <Text style={styles.empty} testID="employees-empty">
              {searched ? t("emp.noResults") : t("emp.empty")}
            </Text>
          }
          renderItem={({ item }) => (
            <Pressable
              testID={`employee-row-${item.emp_id}`}
              onPress={() =>
                router.push({ pathname: "/employees/edit", params: { emp: JSON.stringify(item) } })
              }
              style={({ pressed }) => [styles.row, { opacity: pressed ? 0.85 : 1 }]}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.rowName}>{item.full_name}</Text>
                <Text style={styles.rowSub}>
                  {item.emp_id} · {item.role_code} · {item.department_code}
                </Text>
              </View>
              <ChevronRight size={20} color={colors.muted} strokeWidth={2.2} />
            </Pressable>
          )}
        />

        <BigButton
          testID="add-employee-button"
          label={t("emp.add")}
          icon={UserPlus}
          onPress={() => router.push("/employees/new")}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { flex: 1, padding: sizes.screenPadding, gap: spacing.md },
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    minHeight: 52,
  },
  searchInput: {
    flex: 1,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    paddingVertical: spacing.sm,
  },
  empty: {
    textAlign: "center",
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
    marginTop: spacing.xxl,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginTop: spacing.sm,
  },
  rowName: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  rowSub: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, marginTop: 2 },
});
