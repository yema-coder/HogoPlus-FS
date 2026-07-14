import { CircleCheck } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

interface Props {
  options: string[];
  value: string | undefined;
  onChange: (v: string) => void;
  error?: boolean;
  testID: string;
}

export function prettyOption(opt: string): string {
  return opt.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Full-width option cards (radio behaviour); 2-column grid when >6 options. */
export function SelectFieldInput({ options, value, onChange, error, testID }: Props) {
  const twoCol = options.length > 6;
  return (
    <View style={[styles.wrap, twoCol && styles.grid]}>
      {options.map((opt) => {
        const active = value === opt;
        return (
          <Pressable
            key={opt}
            testID={`${testID}-${opt}`}
            accessibilityRole="radio"
            accessibilityState={{ selected: active }}
            onPress={() => onChange(opt)}
            style={[
              styles.card,
              twoCol && styles.cardHalf,
              active && styles.cardActive,
              error && !value && styles.cardError,
            ]}
          >
            <Text style={[styles.cardText, active && styles.cardTextActive]} numberOfLines={2}>
              {prettyOption(opt)}
            </Text>
            {active ? <CircleCheck size={22} color={colors.primary} strokeWidth={2.4} /> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  grid: { flexDirection: "row", flexWrap: "wrap" },
  card: {
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  cardHalf: { flexBasis: "48%", flexGrow: 1 },
  cardActive: { borderColor: colors.primary, backgroundColor: colors.brandTertiary },
  cardError: { borderColor: colors.danger },
  cardText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text, flexShrink: 1 },
  cardTextActive: { color: colors.primary },
});
