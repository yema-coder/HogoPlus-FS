import { useRouter } from "expo-router";
import { AlertTriangle, Trash2 } from "lucide-react-native";
import React, { useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { deleteAccountConfirm, deleteAccountRequest } from "@/src/api/endpoints";
import { BigButton } from "@/src/components/BigButton";
import { ConfirmModal } from "@/src/components/ConfirmModal";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/** v1.0.25 App-Store compliance: in-app account deletion.
 * Warning (MR/HI/EN via i18n) → confirm → OTP re-verify → deleted + signed out.
 * Demo/reviewer accounts get a clear 409 from the server. */
export default function DeleteAccountScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const logout = useAuthStore((s) => s.logout);
  const profile = useAuthStore((s) => s.profile);
  const [step, setStep] = useState<"warn" | "otp">("warn");
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");

  const detailMsg = (e: unknown): string => {
    if (e instanceof ApiError) {
      const d = e.detail as Record<string, string> | string;
      if (typeof d === "object" && d) {
        const lang = t("common.langCode", { defaultValue: "" }) || "";
        return d[lang] || d.mr || d.en || t("errors.server");
      }
      if (typeof d === "string") return d;
    }
    return t("errors.server");
  };

  const sendOtp = async () => {
    setConfirm(false);
    setBusy(true);
    setError("");
    try {
      await deleteAccountRequest();
      setStep("otp");
      showToast(t("del.otpSent"), "success");
    } catch (e) {
      setError(detailMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    setBusy(true);
    setError("");
    try {
      await deleteAccountConfirm(otp.trim());
      showToast(t("del.done"), "success");
      await logout();
      router.replace("/(auth)/phone");
    } catch (e) {
      setError(detailMsg(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="delete-account-screen">
      <ScreenHeader title={t("del.title")} />
      <KeyboardAwareScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.hero}>
          <AlertTriangle size={44} color={colors.danger} strokeWidth={2.2} />
        </View>
        {step === "warn" ? (
          <>
            <Text style={styles.title}>{t("del.warnTitle")}</Text>
            <View style={styles.card} testID="delete-gone-card">
              <Text style={styles.cardHead}>{t("del.goneHead")}</Text>
              <Text style={styles.cardBody}>{t("del.goneBody")}</Text>
            </View>
            <View style={[styles.card, { borderColor: colors.border }]} testID="delete-kept-card">
              <Text style={[styles.cardHead, { color: colors.text }]}>{t("del.keptHead")}</Text>
              <Text style={styles.cardBody}>{t("del.keptBody")}</Text>
            </View>
            <Text style={styles.note}>{t("del.noUndo")}</Text>
            <BigButton
              testID="delete-start-button"
              label={t("del.startBtn")}
              icon={Trash2}
              variant="danger"
              loading={busy}
              onPress={() => setConfirm(true)}
              style={{ marginTop: spacing.lg }}
            />
          </>
        ) : (
          <>
            <Text style={styles.title}>{t("del.otpTitle")}</Text>
            <Text style={styles.note}>{t("del.otpHint", { phone: profile?.phone ?? "" })}</Text>
            <TextInput
              testID="delete-otp-input"
              style={styles.otpInput}
              value={otp}
              onChangeText={setOtp}
              keyboardType="number-pad"
              maxLength={6}
              placeholder="······"
              placeholderTextColor={colors.muted}
              autoFocus
            />
            <BigButton
              testID="delete-confirm-button"
              label={t("del.confirmBtn")}
              icon={Trash2}
              variant="danger"
              loading={busy}
              disabled={otp.trim().length !== 6}
              onPress={() => void confirmDelete()}
              style={{ marginTop: spacing.lg }}
            />
          </>
        )}
        {error ? (
          <Text style={styles.error} testID="delete-error">
            {error}
          </Text>
        ) : null}
      </KeyboardAwareScrollView>
      <ConfirmModal
        visible={confirm}
        title={t("del.confirmModal")}
        confirmLabel={t("del.startBtn")}
        danger
        onConfirm={() => void sendOtp()}
        onCancel={() => setConfirm(false)}
        testIDPrefix="delete-account"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md },
  hero: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: "#FDE3E7",
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "center",
  },
  title: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
    textAlign: "center",
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: colors.danger,
    padding: spacing.lg,
    gap: spacing.xs,
  },
  cardHead: { fontFamily: fonts.bold, fontSize: type.base, color: colors.danger },
  cardBody: { fontFamily: fonts.regular, fontSize: type.base, color: colors.text, lineHeight: 22 },
  note: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.muted,
    textAlign: "center",
  },
  otpInput: {
    backgroundColor: colors.surface,
    borderWidth: 2,
    borderColor: colors.border,
    borderRadius: radius.md,
    fontFamily: fonts.bold,
    fontSize: 28,
    letterSpacing: 12,
    textAlign: "center",
    paddingVertical: spacing.md,
    color: colors.text,
  },
  error: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.danger,
    textAlign: "center",
  },
});
