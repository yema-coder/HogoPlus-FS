import React from "react";
import { StyleSheet, Switch, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

interface Props {
  value: boolean;
  onChange: (v: boolean) => void;
  testID: string;
}

export function ToggleFieldInput({ value, onChange, testID }: Props) {
  const { t } = useTranslation();
  return (
    <View style={styles.row}>
      <Text style={[styles.label, !value && styles.labelActive]}>{t("common.no")}</Text>
      <Switch
        testID={testID}
        value={value}
        onValueChange={onChange}
        trackColor={{ false: colors.border, true: colors.primary }}
        thumbColor="#FFFFFF"
        style={styles.switch}
      />
      <Text style={[styles.label, value && styles.labelActive]}>{t("common.yes")}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.lg,
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    justifyContent: "center",
  },
  switch: { transform: [{ scaleX: 1.3 }, { scaleY: 1.3 }] },
  label: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.muted },
  labelActive: { color: colors.primary },
});
