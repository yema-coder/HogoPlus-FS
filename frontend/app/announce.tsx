import { useRouter } from "expo-router";
import { Megaphone } from "lucide-react-native";
import React, { useEffect, useMemo, useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { listDepartments, sendAnnouncement } from "@/src/api/endpoints";
import type { DepartmentItem } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { tri } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/** Prompt 17 Part F: announcement composer. Managers → own department only;
 * CGM/MD → any department or everyone. Recipients get an in-app alert + push. */
export default function AnnounceScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const rank = profile?.role?.rank ?? 6;
  const isTop = rank <= 2;

  const [departments, setDepartments] = useState<DepartmentItem[]>([]);
  const [audience, setAudience] = useState<"all" | "department">("department");
  const [deptCode, setDeptCode] = useState<string>(profile?.department_code ?? "");
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!isTop) return;
    void listDepartments().then(setDepartments).catch(() => undefined);
  }, [isTop]);

  const deptLabel = useMemo(() => {
    if (!isTop) return profile?.department ? tri(profile.department as unknown as Record<string, unknown>, "name") : deptCode;
    const d = departments.find((x) => x.code === deptCode);
    return d ? tri(d as unknown as Record<string, unknown>, "name") : deptCode;
  }, [isTop, profile, departments, deptCode]);

  const canSend = title.trim().length >= 2 && message.trim().length >= 2 && (audience === "all" || !!deptCode);

  const submit = async () => {
    if (!canSend || sending) return;
    setSending(true);
    try {
      const res = await sendAnnouncement({
        title: title.trim(),
        message: message.trim(),
        audience,
        department_code: audience === "department" ? deptCode : undefined,
      });
      showToast(t("announce.sent", { count: res.recipients }), "success");
      if (router.canGoBack()) router.back();
      else router.replace("/(tabs)/home");
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else if (e instanceof ApiError && e.status === 403) showToast(t("announce.notAllowed"), "error");
      else showToast(t("errors.server"), "error");
    } finally {
      setSending(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="announce-screen">
      <ScreenHeader title={t("announce.title")} />
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        bottomOffset={24}
      >
          <View style={styles.hero}>
            <Megaphone size={32} color={colors.primary} strokeWidth={2} />
            <Text style={styles.heroText}>{t("announce.heading")}</Text>
          </View>

          <Text style={styles.label}>{t("announce.audience")}</Text>
          {isTop ? (
            <View style={styles.chipsWrap}>
              <Pressable
                testID="announce-audience-all"
                onPress={() => setAudience("all")}
                style={[styles.chip, audience === "all" && styles.chipActive]}
              >
                <Text style={[styles.chipText, audience === "all" && styles.chipTextActive]}>
                  {t("announce.allEmployees")}
                </Text>
              </Pressable>
              {departments.map((d) => (
                <Pressable
                  key={d.code}
                  testID={`announce-dept-${d.code}`}
                  onPress={() => {
                    setAudience("department");
                    setDeptCode(d.code);
                  }}
                  style={[
                    styles.chip,
                    audience === "department" && deptCode === d.code && styles.chipActive,
                  ]}
                >
                  <Text
                    style={[
                      styles.chipText,
                      audience === "department" && deptCode === d.code && styles.chipTextActive,
                    ]}
                  >
                    {tri(d as unknown as Record<string, unknown>, "name")}
                  </Text>
                </Pressable>
              ))}
            </View>
          ) : (
            <View style={styles.fixedDept} testID="announce-own-dept">
              <Text style={styles.fixedDeptText}>
                {t("announce.myDept")}: {deptLabel}
              </Text>
            </View>
          )}

          <Text style={styles.label}>{t("announce.titleLabel")}</Text>
          <TextInput
            testID="announce-title-input"
            style={styles.input}
            value={title}
            onChangeText={setTitle}
            placeholder={t("announce.titleLabel")}
            placeholderTextColor={colors.muted}
            maxLength={120}
          />

          <Text style={styles.label}>{t("announce.messageLabel")}</Text>
          <TextInput
            testID="announce-message-input"
            style={[styles.input, styles.messageInput]}
            value={message}
            onChangeText={setMessage}
            placeholder={t("announce.messageLabel")}
            placeholderTextColor={colors.muted}
            multiline
            maxLength={1000}
          />

          <BigButton
            testID="announce-send-button"
            label={t("announce.send")}
            icon={Megaphone}
            loading={sending}
            disabled={!canSend}
            onPress={() => void submit()}
          />
      </KeyboardAwareScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { padding: sizes.screenPadding, gap: spacing.sm, paddingBottom: spacing.xxl },
  hero: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  heroText: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, flex: 1 },
  label: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.muted,
    marginTop: spacing.md,
  },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    minHeight: 44,
    justifyContent: "center",
  },
  chipActive: { borderColor: colors.primary, backgroundColor: colors.primary },
  chipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  chipTextActive: { color: colors.onPrimary },
  fixedDept: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  fixedDeptText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    backgroundColor: colors.surface,
  },
  messageInput: { minHeight: 120, textAlignVertical: "top", marginBottom: spacing.lg },
});
