import { Sparkles } from "lucide-react-native";
import React from "react";
import { StyleSheet, Text, View, ActivityIndicator, type LayoutChangeEvent } from "react-native";
import { useTranslation } from "react-i18next";

import type { FormFieldDef } from "@/src/api/types";
import { tri } from "@/src/i18n";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

interface Props {
  field: FormFieldDef;
  error?: string;
  children: React.ReactNode;
  onLayout?: (e: LayoutChangeEvent) => void;
  /** confidence 0-1 when the value was auto-filled by AI (true = filled, unknown confidence) */
  aiFilled?: number | true;
  aiLoading?: boolean;
}

/** Trilingual label + AI badge + inline error, wrapping any field input. */
export function FieldWrapper({ field, error, children, onLayout, aiFilled, aiLoading }: Props) {
  const { t } = useTranslation();
  return (
    <View style={styles.wrap} onLayout={onLayout} testID={`field-${field.key}`}>
      <View style={styles.labelRow}>
        <Text style={styles.label}>
          {tri(field as unknown as Record<string, unknown>, "label")}
          {field.required ? <Text style={styles.star}> *</Text> : null}
        </Text>
        {aiFilled !== undefined ? (
          <View style={styles.aiFilledChip} testID={`ai-filled-${field.key}`}>
            <Sparkles size={12} color={colors.success} strokeWidth={2.4} />
            <Text style={styles.aiFilledText}>
              {typeof aiFilled === "number" ? `AI ${Math.round(aiFilled * 100)}%` : "AI"}
            </Text>
          </View>
        ) : field.ai_hook ? (
          <View style={styles.aiBadge} testID={`ai-badge-${field.key}`}>
            <Sparkles size={12} color={colors.onPrimary} strokeWidth={2.4} />
            <Text style={styles.aiBadgeText}>AI</Text>
          </View>
        ) : null}
      </View>
      {aiLoading ? (
        <View style={styles.aiLoadingRow} testID={`ai-loading-${field.key}`}>
          <ActivityIndicator size="small" color={colors.accent} />
          <Text style={styles.aiLoadingText}>{t("ai.reading")}</Text>
        </View>
      ) : field.ai_hook && aiFilled === undefined ? (
        <Text style={styles.aiHint}>{t("forms.aiHint")}</Text>
      ) : null}
      {children}
      {error ? (
        <Text style={styles.error} testID={`field-error-${field.key}`}>
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs, marginBottom: spacing.lg },
  labelRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  label: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text, flexShrink: 1 },
  star: { color: colors.danger },
  aiBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  aiBadgeText: { fontFamily: fonts.bold, fontSize: 11, color: colors.onPrimary },
  aiFilledChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: "#E4F4E8",
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  aiFilledText: { fontFamily: fonts.bold, fontSize: 11, color: colors.success },
  aiLoadingRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  aiLoadingText: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.accent },
  aiHint: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  error: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.danger },
});
