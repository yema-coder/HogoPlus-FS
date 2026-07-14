import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import React from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ScreenHeader } from "@/src/components/ScreenHeader";
import { INCIDENT_CATEGORIES, type CategoryDef } from "@/src/constants/categories";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/** Tap 1 of the 3-tap incident flow: pick what happened. */
export default function IncidentCategory() {
  const router = useRouter();
  const { t } = useTranslation();

  const renderItem = ({ item }: { item: CategoryDef }) => {
    const Icon = item.icon;
    return (
      <Pressable
        testID={`category-${item.code}`}
        accessibilityRole="button"
        onPress={() => {
          void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => undefined);
          router.push({ pathname: "/incident/capture", params: { category: item.code } });
        }}
        style={({ pressed }) => [styles.tile, { opacity: pressed ? 0.85 : 1 }]}
      >
        <View style={[styles.iconCircle, { backgroundColor: `${item.tint}18` }]}>
          <Icon size={40} color={item.tint} strokeWidth={2.2} />
        </View>
        <Text style={styles.label} numberOfLines={1}>
          {t(item.tKey)}
        </Text>
      </Pressable>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="incident-category-screen">
      <ScreenHeader title={t("incident.chooseCategory")} />
      <FlatList
        data={INCIDENT_CATEGORIES}
        keyExtractor={(c) => c.code}
        renderItem={renderItem}
        numColumns={2}
        columnWrapperStyle={{ gap: spacing.md }}
        contentContainerStyle={styles.list}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  list: { padding: sizes.screenPadding, gap: spacing.md },
  tile: {
    flex: 1,
    minHeight: sizes.categoryCircle + 40,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    paddingVertical: spacing.lg,
  },
  iconCircle: {
    width: 80,
    height: 80,
    borderRadius: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  label: { fontFamily: fonts.semiBold, fontSize: type.lg, color: colors.text },
});
