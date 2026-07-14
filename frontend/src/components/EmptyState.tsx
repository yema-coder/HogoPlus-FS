import type { LucideIcon } from "lucide-react-native";
import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, fonts, spacing, type } from "@/src/theme/tokens";

interface Props {
  icon: LucideIcon;
  title: string;
  body?: string;
  testID?: string;
}

export function EmptyState({ icon: Icon, title, body, testID = "empty-state" }: Props) {
  return (
    <View style={styles.wrap} testID={testID}>
      <View style={styles.circle}>
        <Icon size={40} color={colors.muted} strokeWidth={1.8} />
      </View>
      <Text style={styles.title}>{title}</Text>
      {body ? <Text style={styles.body}>{body}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: "center",
    paddingVertical: spacing.xxxl,
    paddingHorizontal: spacing.xl,
  },
  circle: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  title: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
    textAlign: "center",
  },
  body: {
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.xs,
  },
});
