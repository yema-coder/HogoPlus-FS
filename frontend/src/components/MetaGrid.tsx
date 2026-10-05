// Clean 2-column metadata grid used on the incident detail screen. Each cell is
// a label + value (value may be plain text or a node like a status chip).

import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

export interface MetaItem {
  key: string;
  label: string;
  value: React.ReactNode;
}

export function MetaGrid({ items, testID = "meta-grid" }: { items: MetaItem[]; testID?: string }) {
  if (items.length === 0) return null;
  return (
    <View style={styles.grid} testID={testID}>
      {items.map((it) => (
        <View key={it.key} style={styles.cell} testID={`meta-${it.key}`}>
          <Text style={styles.label}>{it.label}</Text>
          {typeof it.value === "string" || typeof it.value === "number" ? (
            <Text style={styles.value}>{it.value}</Text>
          ) : (
            <View style={styles.valueNode}>{it.value}</View>
          )}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  cell: { width: "50%", paddingVertical: spacing.sm, paddingRight: spacing.sm, gap: 4 },
  label: {
    fontFamily: fonts.medium,
    fontSize: type.xs,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  value: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  valueNode: { flexDirection: "row", alignItems: "center" },
});
