import { useRouter } from "expo-router";
import { Languages } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import i18n, { LANGUAGES, type AppLanguage } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { storage } from "@/src/utils/storage";

export default function LanguagePicker() {
  const router = useRouter();
  const { t } = useTranslation();
  const markLangPicked = useAuthStore((s) => s.markLangPicked);

  const choose = async (code: AppLanguage) => {
    await i18n.changeLanguage(code);
    await storage.setItem("hogo.lang", code);
    await markLangPicked();
    router.replace("/(auth)/phone");
  };

  return (
    <SafeAreaView style={styles.safe} testID="language-picker-screen">
      <View style={styles.top}>
        <View style={styles.logoCircle}>
          <Languages size={44} color={colors.onPrimary} strokeWidth={2} />
        </View>
        <Text style={styles.appName}>Hogo Plus</Text>
        <Text style={styles.title}>{t("lang.title")}</Text>
        <Text style={styles.subtitle}>{t("lang.subtitle")}</Text>
      </View>
      <View style={styles.buttons}>
        {LANGUAGES.map((l) => (
          <Pressable
            key={l.code}
            testID={`language-option-${l.code}`}
            accessibilityRole="button"
            onPress={() => void choose(l.code)}
            style={({ pressed }) => [styles.langBtn, { opacity: pressed ? 0.85 : 1 }]}
          >
            <Text style={styles.langText}>{l.native}</Text>
          </Pressable>
        ))}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
    padding: sizes.screenPadding,
    justifyContent: "space-between",
  },
  top: {
    alignItems: "center",
    marginTop: spacing.xxxl,
    gap: spacing.sm,
  },
  logoCircle: {
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.md,
  },
  appName: {
    fontFamily: fonts.bold,
    fontSize: type.xxl,
    color: colors.primary,
  },
  title: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
    marginTop: spacing.lg,
  },
  subtitle: {
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
  },
  buttons: {
    gap: spacing.lg,
    marginBottom: spacing.xxl,
  },
  langBtn: {
    height: 72,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 2,
    borderColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  langText: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.primary,
  },
});
