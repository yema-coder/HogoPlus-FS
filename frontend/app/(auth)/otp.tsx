import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useEffect, useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { sendOtp, verifyOtp } from "@/src/api/endpoints";
import { BigButton } from "@/src/components/BigButton";
import { showToast } from "@/src/components/Toast";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

const RESEND_SECONDS = 30;

export default function OtpEntry() {
  const router = useRouter();
  const { t } = useTranslation();
  const { phone } = useLocalSearchParams<{ phone: string }>();
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const [seconds, setSeconds] = useState(RESEND_SECONDS);
  const inputRef = useRef<TextInput>(null);
  const submittedFor = useRef<string | null>(null);
  const setSession = useAuthStore((s) => s.setSession);
  const setRegistration = useAuthStore((s) => s.setRegistration);

  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(timer);
  }, []);

  const submit = async (code: string) => {
    if (!phone || loading) return;
    setLoading(true);
    try {
      const res = await verifyOtp(phone, code);
      if (res.is_new) {
        setRegistration(res.registration_token, phone);
        router.replace("/(auth)/register-name");
        return;
      }
      await setSession(
        { access_token: res.access_token, refresh_token: res.refresh_token },
        res.employee,
      );
      if (res.employee.onboarding_status !== "approved") router.replace("/(auth)/pending");
      else router.replace("/(tabs)/home");
    } catch (e) {
      setOtp("");
      submittedFor.current = null;
      if (e instanceof ApiError && e.status === 429) showToast(t("auth.locked"), "error");
      else if (e instanceof ApiError && e.status === 401) showToast(t("auth.invalidOtp"), "error");
      else if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else showToast(t("errors.server"), "error");
    } finally {
      setLoading(false);
    }
  };

  const onChange = (v: string) => {
    const clean = v.replace(/\D/g, "").slice(0, 6);
    setOtp(clean);
    if (clean.length === 6 && submittedFor.current !== clean) {
      submittedFor.current = clean;
      void submit(clean);
    }
  };

  const resend = async () => {
    if (!phone) return;
    try {
      await sendOtp(phone);
      setSeconds(RESEND_SECONDS);
      showToast(t("auth.otpSent", { phone }), "success");
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) showToast(t("auth.locked"), "error");
      else showToast(t("errors.server"), "error");
    }
  };

  return (
    <SafeAreaView style={styles.safe} testID="otp-entry-screen">
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.title}>{t("auth.otpTitle")}</Text>
          <Text style={styles.hint}>{t("auth.otpSent", { phone })}</Text>

          <Pressable
            style={styles.boxes}
            onPress={() => inputRef.current?.focus()}
            testID="otp-boxes"
          >
            {Array.from({ length: 6 }).map((_, i) => (
              <View
                key={i}
                style={[styles.box, i === otp.length && styles.boxActive]}
                testID={`otp-box-${i}`}
              >
                <Text style={styles.boxText}>{otp[i] ?? ""}</Text>
              </View>
            ))}
          </Pressable>
          <TextInput
            ref={inputRef}
            testID="otp-input"
            style={styles.hiddenInput}
            value={otp}
            onChangeText={onChange}
            keyboardType="number-pad"
            maxLength={6}
            autoFocus
          />

          <BigButton
            testID="verify-otp-button"
            label={t("auth.verify")}
            onPress={() => void submit(otp)}
            loading={loading}
            disabled={otp.length !== 6}
            height={64}
            style={{ marginTop: spacing.xl }}
          />

          <View style={styles.footer}>
            {seconds > 0 ? (
              <Text style={styles.resendIn}>{t("auth.resendIn", { s: seconds })}</Text>
            ) : (
              <Pressable onPress={() => void resend()} testID="resend-otp-button" style={styles.linkBtn}>
                <Text style={styles.link}>{t("auth.resend")}</Text>
              </Pressable>
            )}
            <Pressable onPress={() => router.back()} testID="change-phone-button" style={styles.linkBtn}>
              <Text style={styles.link}>{t("auth.changePhone")}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, flexGrow: 1, paddingTop: spacing.xxxl },
  title: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.text },
  hint: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted, marginTop: spacing.xs },
  boxes: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.xl,
    justifyContent: "center",
  },
  box: {
    flex: 1,
    maxWidth: 60,
    height: 64,
    borderRadius: radius.sm,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  boxActive: { borderColor: colors.primary },
  boxText: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.text },
  hiddenInput: { position: "absolute", opacity: 0.01, height: 1, width: 1 },
  footer: { marginTop: spacing.xl, alignItems: "center", gap: spacing.sm },
  resendIn: { fontFamily: fonts.medium, fontSize: type.base, color: colors.muted },
  linkBtn: { minHeight: sizes.touchTarget, justifyContent: "center", paddingHorizontal: spacing.lg },
  link: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.accent },
});
