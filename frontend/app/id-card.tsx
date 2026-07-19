import * as Sharing from "expo-sharing";
import { Share2 } from "lucide-react-native";
import React, { useRef } from "react";
import { Image, Platform, ScrollView, StyleSheet, Text, View } from "react-native";
import QRCode from "react-native-qrcode-svg";
import { SafeAreaView } from "react-native-safe-area-context";
import ViewShot from "react-native-view-shot";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { tri } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, shadow, sizes, spacing, type } from "@/src/theme/tokens";

/** Digital ID card (Prompt 16): read-only from existing profile data, QR encodes
 * emp_id — handy for gate checks. Shareable as an image via view-shot. */
export default function IdCardScreen() {
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const shotRef = useRef<ViewShot>(null);

  const dept = profile?.department
    ? tri(profile.department as unknown as Record<string, unknown>, "name")
    : (profile?.department_code ?? "—");
  const role = profile?.role
    ? tri(profile.role as unknown as Record<string, unknown>, "label")
    : (profile?.role_code ?? "—");
  const selfie = profile?.selfie_url ?? null;

  const share = async () => {
    try {
      const uri = await shotRef.current?.capture?.();
      if (uri && (await Sharing.isAvailableAsync())) {
        await Sharing.shareAsync(uri, { mimeType: "image/png" });
      } else {
        showToast(t("errors.server"), "error");
      }
    } catch {
      showToast(t("errors.server"), "error");
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="idcard-screen">
      <ScreenHeader title={t("idcard.title")} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <ViewShot ref={shotRef} options={{ format: "png", quality: 1 }}>
          <View style={[styles.card, shadow.card]} testID="idcard-card">
            <View style={styles.cardHead}>
              <Image
                source={require("@/assets/images/logo.png")}
                style={styles.logo}
                resizeMode="contain"
              />
              <Text style={styles.company}>HogoPlus-FS</Text>
            </View>
            <View style={styles.cardBody}>
              {selfie ? (
                <Image source={{ uri: selfie }} style={styles.selfie} />
              ) : (
                <View style={[styles.selfie, styles.selfieFallback]}>
                  <Text style={styles.selfieInitials}>
                    {(profile?.full_name ?? "?")
                      .split(/\s+/)
                      .slice(0, 2)
                      .map((w) => w.charAt(0).toUpperCase())
                      .join("")}
                  </Text>
                </View>
              )}
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={styles.name}>{profile?.full_name}</Text>
                <Text style={styles.meta}>
                  {t("profile.empId")}: <Text style={styles.metaStrong}>{profile?.emp_id}</Text>
                </Text>
                <Text style={styles.meta}>{dept}</Text>
                <Text style={styles.meta}>{role}</Text>
              </View>
            </View>
            <View style={styles.qrRow}>
              <QRCode value={profile?.emp_id || "?"} size={104} color={colors.text} />
              <Text style={styles.qrHint}>{t("idcard.hint")}</Text>
            </View>
          </View>
        </ViewShot>
        {Platform.OS !== "web" ? (
          <BigButton
            testID="idcard-share"
            label={t("idcard.share")}
            icon={Share2}
            variant="outline"
            onPress={() => void share()}
          />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.lg, paddingBottom: spacing.xxl },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 2,
    borderColor: colors.primary,
    overflow: "hidden",
  },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: colors.brandTertiary,
    paddingVertical: spacing.md,
  },
  logo: { width: 32, height: 26 },
  company: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.primary },
  cardBody: { flexDirection: "row", gap: spacing.lg, padding: spacing.lg, alignItems: "center" },
  selfie: { width: 96, height: 96, borderRadius: radius.md, backgroundColor: colors.border },
  selfieFallback: { alignItems: "center", justifyContent: "center", backgroundColor: colors.primary },
  selfieInitials: { fontFamily: fonts.bold, fontSize: type.xxl, color: colors.onPrimary },
  name: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  meta: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  metaStrong: { fontFamily: fonts.bold, color: colors.text },
  qrRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    padding: spacing.lg,
  },
  qrHint: { flex: 1, fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
});
