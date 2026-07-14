import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { colors, fonts, radius } from "@/src/theme/tokens";

const TINTS: Record<string, { bg: string; fg: string }> = {
  normal: { bg: colors.surfaceTertiary, fg: colors.muted },
  high: { bg: "#FCEEDB", fg: "#B26A00" },
  critical: { bg: "#FDE3E7", fg: colors.danger },
};

export function SeverityChip({ severity, testID }: { severity: string; testID?: string }) {
  const { t } = useTranslation();
  const tint = TINTS[severity] ?? TINTS.normal;
  return (
    <View style={[styles.chip, { backgroundColor: tint.bg }]} testID={testID}>
      <Text style={[styles.text, { color: tint.fg }]}>{t(`severity.${severity}`)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    alignSelf: "flex-start",
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  text: { fontFamily: fonts.bold, fontSize: 12 },
});
