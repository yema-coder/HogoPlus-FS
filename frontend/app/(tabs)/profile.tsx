import { useRouter } from "expo-router";
import { LogOut } from "lucide-react-native";
import React, { useState } from "react";
import { ScrollView, StyleSheet, Text, Pressable, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { patchMe } from "@/src/api/endpoints";
import { BigButton } from "@/src/components/BigButton";
import { ConfirmModal } from "@/src/components/ConfirmModal";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import i18n, { LANGUAGES, tri, type AppLanguage } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { storage } from "@/src/utils/storage";

export default function ProfileScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const logout = useAuthStore((s) => s.logout);
  const [confirmOut, setConfirmOut] = useState(false);

  const initials = (profile?.full_name ?? "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w.charAt(0).toUpperCase())
    .join("");

  const changeLang = async (code: AppLanguage) => {
    await i18n.changeLanguage(code);
    await storage.setItem("hogo.lang", code);
    patchMe({ language_pref: code }).catch(() => undefined);
  };

  const rows: { label: string; value: string }[] = [
    { label: t("profile.empId"), value: profile?.emp_id ?? "—" },
    {
      label: t("profile.department"),
      value: profile?.department
        ? tri(profile.department as unknown as Record<string, unknown>, "name")
        : (profile?.department_code ?? "—"),
    },
    {
      label: t("profile.role"),
      value: profile?.role
        ? tri(profile.role as unknown as Record<string, unknown>, "label")
        : (profile?.role_code ?? "—"),
    },
  ];

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="profile-screen">
      <ScreenHeader title={t("profile.title")} back={false} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.hero}>
          <View style={styles.avatar} testID="profile-avatar">
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
          <Text style={styles.name}>{profile?.full_name}</Text>
          <Text style={styles.phone}>{profile?.phone ?? ""}</Text>
        </View>

        <View style={styles.card}>
          {rows.map((r, idx) => (
            <View key={r.label} style={[styles.infoRow, idx > 0 && styles.infoRowBorder]}>
              <Text style={styles.infoLabel}>{r.label}</Text>
              <Text style={styles.infoValue} numberOfLines={1}>
                {r.value}
              </Text>
            </View>
          ))}
        </View>

        <Text style={styles.sectionTitle}>{t("profile.language")}</Text>
        <View style={styles.langRow}>
          {LANGUAGES.map((l) => {
            const active = i18n.language === l.code;
            return (
              <Pressable
                key={l.code}
                testID={`profile-lang-${l.code}`}
                accessibilityRole="button"
                onPress={() => void changeLang(l.code)}
                style={[styles.langBtn, active && styles.langBtnActive]}
              >
                <Text style={[styles.langText, active && styles.langTextActive]}>{l.native}</Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={styles.note}>{t("profile.memberNote")}</Text>

        <BigButton
          testID="logout-button"
          label={t("profile.logout")}
          icon={LogOut}
          variant="muted"
          onPress={() => setConfirmOut(true)}
          style={{ marginTop: spacing.lg }}
        />
      </ScrollView>

      <ConfirmModal
        visible={confirmOut}
        title={t("common.confirmLogout")}
        confirmLabel={t("common.logout")}
        danger
        onConfirm={() => {
          setConfirmOut(false);
          void logout().then(() => router.replace("/(auth)/phone"));
        }}
        onCancel={() => setConfirmOut(false)}
        testIDPrefix="logout"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.xxl },
  hero: { alignItems: "center", gap: spacing.xs, marginVertical: spacing.md },
  avatar: {
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  avatarText: { fontFamily: fonts.bold, fontSize: type.xxl, color: colors.onPrimary },
  name: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.text },
  phone: { fontFamily: fonts.medium, fontSize: type.base, color: colors.muted },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  infoRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    minHeight: 56,
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
  },
  infoRowBorder: { borderTopWidth: 1, borderTopColor: colors.border },
  infoLabel: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted },
  infoValue: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.text,
    flexShrink: 1,
    textAlign: "right",
  },
  sectionTitle: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
    marginTop: spacing.md,
  },
  langRow: { flexDirection: "row", gap: spacing.sm },
  langBtn: {
    flex: 1,
    height: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  langBtnActive: { borderColor: colors.primary, backgroundColor: colors.brandTertiary },
  langText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  langTextActive: { color: colors.primary },
  note: {
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.md,
  },
});
