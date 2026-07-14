import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { colors, fonts, radius, statusColors } from "@/src/theme/tokens";

export function StatusChip({ status, testID }: { status: string; testID?: string }) {
  const { t } = useTranslation();
  const bg = statusColors[status] ?? colors.muted;
  return (
    <View style={[styles.chip, { backgroundColor: bg }]} testID={testID ?? `status-chip-${status}`}>
      <Text style={styles.text}>{t(`status.${status}`)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 4,
    alignSelf: "flex-start",
    flexShrink: 0,
  },
  text: {
    fontFamily: fonts.semiBold,
    fontSize: 13,
    color: "#FFFFFF",
  },
});
