import { WifiOff } from "lucide-react-native";
import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { colors, fonts, spacing, type } from "@/src/theme/tokens";

interface Props {
  onRetry: () => void;
  message?: string;
  testID?: string;
}

export function ErrorRetry({ onRetry, message, testID = "error-retry" }: Props) {
  const { t } = useTranslation();
  return (
    <View style={styles.wrap} testID={testID}>
      <WifiOff size={40} color={colors.muted} strokeWidth={1.8} />
      <Text style={styles.text}>{message ?? t("errors.network")}</Text>
      <BigButton
        testID={`${testID}-button`}
        label={t("common.retry")}
        onPress={onRetry}
        variant="outline"
        style={styles.btn}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: "center",
    paddingVertical: spacing.xxl,
    paddingHorizontal: spacing.xl,
    gap: spacing.lg,
  },
  text: {
    fontFamily: fonts.medium,
    fontSize: type.base,
    color: colors.muted,
    textAlign: "center",
  },
  btn: {
    alignSelf: "stretch",
  },
});
