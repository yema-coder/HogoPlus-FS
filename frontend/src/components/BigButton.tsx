import * as Haptics from "expo-haptics";
import type { LucideIcon } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, ViewStyle } from "react-native";

import { EyeLoader } from "@/src/components/EyeLoader";
import { colors, fonts, radius, sizes, type } from "@/src/theme/tokens";

type Variant = "primary" | "danger" | "success" | "outline" | "muted" | "accent";

const BG: Record<Variant, string> = {
  primary: colors.primary,
  danger: colors.danger,
  success: colors.success,
  accent: colors.accent,
  outline: "transparent",
  muted: colors.surfaceTertiary,
};
const FG: Record<Variant, string> = {
  primary: colors.onPrimary,
  danger: colors.onDanger,
  success: colors.onSuccess,
  accent: colors.onPrimary,
  outline: colors.primary,
  muted: colors.text,
};

interface Props {
  label: string;
  onPress: () => void;
  icon?: LucideIcon;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  height?: number;
  style?: ViewStyle;
  testID: string;
}

export function BigButton({
  label,
  onPress,
  icon: Icon,
  variant = "primary",
  loading = false,
  disabled = false,
  height = sizes.touchTarget,
  style,
  testID,
}: Props) {
  const fg = FG[variant];
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={() => {
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => undefined);
        onPress();
      }}
      style={({ pressed }) => [
        styles.base,
        {
          backgroundColor: BG[variant],
          height,
          opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
          borderWidth: variant === "outline" ? 2 : 0,
          borderColor: colors.primary,
        },
        style,
      ]}
    >
      {loading ? (
        <EyeLoader size={18} />
      ) : (
        <>
          {Icon ? <Icon size={24} color={fg} strokeWidth={2.4} /> : null}
          <Text style={[styles.label, { color: fg }]} numberOfLines={1}>
            {label}
          </Text>
        </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    borderRadius: radius.md,
    paddingHorizontal: 20,
  },
  label: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
  },
});
