import React from "react";
import { StyleSheet, Text } from "react-native";
import { useTranslation } from "react-i18next";

import { colors, fonts } from "@/src/theme/tokens";
import { minutesAgo } from "@/src/utils/format";

/** Subtle "updated Xm ago" note under cached lists. */
export function UpdatedNote({ fetchedAt }: { fetchedAt: number | null }) {
  const { t } = useTranslation();
  if (!fetchedAt) return null;
  const m = minutesAgo(fetchedAt);
  return (
    <Text style={styles.note} testID="updated-note">
      {m < 1 ? t("common.justNow") : t("common.updatedAgo", { m })}
    </Text>
  );
}

const styles = StyleSheet.create({
  note: {
    fontFamily: fonts.regular,
    fontSize: 12,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: 4,
  },
});
