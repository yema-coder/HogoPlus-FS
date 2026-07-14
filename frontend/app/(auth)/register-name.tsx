import { useRouter } from "expo-router";
import React, { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

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
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
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
              router.push({ pathname: "/(auth)/register-department", params: { name: name.trim() } })
            }
            disabled={!valid}
            height={64}
            style={{ marginTop: spacing.xl }}
          />
        </ScrollView>
      </KeyboardAvoidingView>
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
});
