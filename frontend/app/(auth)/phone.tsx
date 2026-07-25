import { useRouter } from "expo-router";
import React, { useState } from "react";
import {
  Image,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, localizedDetail } from "@/src/api/client";
import { sendOtp } from "@/src/api/endpoints";
import { BigButton } from "@/src/components/BigButton";
import { showToast } from "@/src/components/Toast";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

export default function PhoneEntry() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const [digits, setDigits] = useState("");
  const [loading, setLoading] = useState(false);

  const valid = /^[6-9]\d{9}$/.test(digits);

  const submit = async () => {
    if (!valid) {
      showToast(t("auth.invalidPhone"), "error");
      return;
    }
    const phone = `+91${digits}`;
    setLoading(true);
    try {
      await sendOtp(phone);
      router.push({ pathname: "/(auth)/otp", params: { phone } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        // rate limit: backend sends {retry_after_seconds, en, hi, mr}
        showToast(localizedDetail(e, i18n.language || "mr") ?? t("auth.locked"), "error");
      } else if (
        e instanceof ApiError &&
        e.status === 403 &&
        typeof e.detail === "object" &&
        e.detail !== null
      ) {
        // registration guard: backend sends a friendly trilingual {en,hi,mr} message
        const d = e.detail as Record<string, string>;
        const lang = (i18n.language || "mr").slice(0, 2);
        showToast(d[lang] || d.en || t("errors.server"), "error");
      } else if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else showToast(t("errors.server"), "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} testID="phone-entry-screen">
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.hero}>
            <Image
              source={require("@/assets/images/logo.png")}
              style={styles.logoImg}
              resizeMode="contain"
              testID="login-logo"
            />
            <Text style={styles.appName}>HogoPlus-FS</Text>
            <Text style={styles.welcome}>{t("auth.welcome")}</Text>
          </View>

          <Text style={styles.label}>{t("auth.phoneTitle")}</Text>
          <View style={styles.inputRow}>
            <View style={styles.prefix}>
              <Text style={styles.prefixText}>+91</Text>
            </View>
            <TextInput
              testID="phone-input"
              style={styles.input}
              value={digits}
              onChangeText={(v) => setDigits(v.replace(/\D/g, "").slice(0, 10))}
              keyboardType="number-pad"
              maxLength={10}
              placeholder={t("auth.phoneHint")}
              placeholderTextColor={colors.muted}
              autoFocus
              onSubmitEditing={() => void submit()}
            />
          </View>

          <BigButton
            testID="send-otp-button"
            label={t("auth.sendOtp")}
            onPress={() => void submit()}
            loading={loading}
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
  scroll: { padding: sizes.screenPadding, flexGrow: 1 },
  hero: { alignItems: "center", marginVertical: spacing.xxl, gap: spacing.xs },
  logoImg: { width: 120, height: 98, marginBottom: spacing.md },
  appName: { fontFamily: fonts.bold, fontSize: type.xxl, color: colors.primary },
  welcome: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted },
  label: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
    marginBottom: spacing.md,
  },
  inputRow: { flexDirection: "row", gap: spacing.sm },
  prefix: {
    height: 64,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  prefixText: { fontFamily: fonts.semiBold, fontSize: type.xl, color: colors.text },
  input: {
    flex: 1,
    height: 64,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    fontFamily: fonts.semiBold,
    fontSize: type.xl,
    color: colors.text,
    letterSpacing: 2,
  },
});
