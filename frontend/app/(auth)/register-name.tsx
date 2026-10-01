import { useRouter } from "expo-router";
import React, { useState } from "react";
import {
  Linking,
  StyleSheet,
  Text,
  TextInput,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { API_BASE } from "@/src/api/client";
import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

export default function RegisterName() {
  const router = useRouter();
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const valid = name.trim().length >= 2;

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="register-name-screen">
      <ScreenHeader title={t("reg.nameTitle")} />
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        bottomOffset={24}
      >
          <Text style={styles.hint}>{t("reg.nameHint")}</Text>
          <TextInput
            testID="register-name-input"
            style={styles.input}
            value={name}
            onChangeText={setName}
            placeholder={t("reg.nameTitle")}
            placeholderTextColor={colors.muted}
            autoFocus
            autoCapitalize="words"
          />
          <BigButton
            testID="register-name-next-button"
            label={t("common.next")}
            onPress={() =>
              router.push({ pathname: "/(auth)/register-selfie", params: { name: name.trim() } })
            }
            disabled={!valid}
            height={64}
            style={{ marginTop: spacing.xl }}
          />
          <Text style={styles.privacyLine}>
            {t("reg.privacyPrefix")}{" "}
            <Text
              testID="register-privacy-link"
              style={styles.privacyLink}
              onPress={() => void Linking.openURL(`${API_BASE}/legal/privacy`)}
            >
              {t("reg.privacyLink")}
            </Text>
          </Text>
      </KeyboardAwareScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding },
  hint: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted, marginBottom: spacing.md },
  input: {
    height: 64,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
  },
  privacyLine: {
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.lg,
  },
  privacyLink: { fontFamily: fonts.bold, color: colors.accent, textDecorationLine: "underline" },
});
