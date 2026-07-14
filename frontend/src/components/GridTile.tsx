import * as Haptics from "expo-haptics";
import type { LucideIcon } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, radius, shadow, spacing, type } from "@/src/theme/tokens";

interface Props {
  label: string;
  icon: LucideIcon;
  onPress: () => void;
  sub?: string;
  badge?: number;
  tint?: string;
  testID: string;
}

export function GridTile({ label, icon: Icon, onPress, sub, badge, tint = colors.primary, testID }: Props) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      onPress={() => {
        void Haptics.selectionAsync().catch(() => undefined);
        onPress();
      }}
      style={({ pressed }) => [styles.tile, shadow.card, { opacity: pressed ? 0.85 : 1 }]}
    >
      <View style={[styles.iconWrap, { backgroundColor: `${tint}14` }]}>
        <Icon size={30} color={tint} strokeWidth={2.2} />
      </View>
      <Text style={styles.label} numberOfLines={1}>
        {label}
      </Text>
      {sub ? (
        <Text style={styles.sub} numberOfLines={1}>
          {sub}
        </Text>
      ) : null}
      {badge && badge > 0 ? (
        <View style={styles.badge} testID={`${testID}-badge`}>
          <Text style={styles.badgeText}>{badge > 99 ? "99+" : badge}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tile: {
    flex: 1,
    minHeight: 120,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    justifyContent: "center",
  },
  iconWrap: {
    width: 48,
    height: 48,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  label: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.text,
  },
  sub: {
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
  },
  badge: {
    position: "absolute",
    top: 12,
    right: 12,
    minWidth: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.danger,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 6,
  },
  badgeText: {
    fontFamily: fonts.bold,
    fontSize: 13,
    color: colors.onDanger,
  },
});
