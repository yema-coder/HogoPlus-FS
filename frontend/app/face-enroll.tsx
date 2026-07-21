import * as ImageManipulator from "expo-image-manipulator";
import { useRouter } from "expo-router";
import { ScanFace } from "lucide-react-native";
import React, { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "@/src/api/client";
import { faceEnroll } from "@/src/api/endpoints";
import { BigButton } from "@/src/components/BigButton";
import { EyeLoader } from "@/src/components/EyeLoader";
import { SelfieCamera } from "@/src/components/SelfieCamera";
import { showToast } from "@/src/components/Toast";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/**
 * Prompt 17 Part C: one-time face enrollment right after login when no
 * reference selfie exists. Reuses the EXISTING bootstrap fields server-side —
 * skippable ("नंतर करा"): the first-punch bootstrap still covers skippers.
 */
export default function FaceEnrollScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const refreshProfile = useAuthStore((s) => s.refreshProfile);
  const markFaceEnrollAsked = useAuthStore((s) => s.markFaceEnrollAsked);
  const [capturing, setCapturing] = useState(false);
  const [saving, setSaving] = useState(false);

  const finish = async () => {
    await markFaceEnrollAsked();
    router.replace("/(tabs)/home");
  };

  const submit = async (uri: string) => {
    setSaving(true);
    try {
      let selfieUri = uri;
      try {
        const compressed = await ImageManipulator.manipulateAsync(
          uri,
          [{ resize: { width: 720 } }],
          { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG },
        );
        selfieUri = compressed.uri;
      } catch {
        // upload original if compression fails
      }
      const uploaded = await uploadFile(selfieUri, "face-enroll.jpg");
      await faceEnroll(uploaded.key);
      await refreshProfile();
      showToast(t("face.success"), "success");
      await finish();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // reference already exists (e.g. set meanwhile) — nothing to do
        await refreshProfile();
        await finish();
      } else if (e instanceof ApiError && e.status === 0) {
        showToast(t("errors.network"), "error");
        setCapturing(false);
      } else {
        showToast(t("face.failed"), "error");
        setCapturing(false);
      }
    } finally {
      setSaving(false);
    }
  };

  if (saving) {
    return (
      <SafeAreaView style={styles.safe} testID="face-enroll-saving">
        <View style={styles.center}>
          <EyeLoader size={40} />
          <Text style={styles.savingText}>{t("face.saving")}</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (capturing) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]} testID="face-enroll-camera">
        <SelfieCamera
          hint={t("face.hint")}
          onUse={(uri) => void submit(uri)}
          onClose={() => setCapturing(false)}
          testIDPrefix="face-enroll"
        />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} testID="face-enroll-screen">
      <View style={styles.center}>
        <View style={styles.iconWrap}>
          <ScanFace size={56} color={colors.primary} strokeWidth={1.8} />
        </View>
        <Text style={styles.title}>{t("face.title")}</Text>
        <Text style={styles.body}>{t("face.body")}</Text>
      </View>
      <View style={styles.actions}>
        <BigButton
          testID="face-enroll-start"
          label={t("face.start")}
          onPress={() => setCapturing(true)}
        />
        <BigButton
          testID="face-enroll-later"
          label={t("face.later")}
          variant="outline"
          onPress={() => void finish()}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: sizes.screenPadding,
    gap: spacing.lg,
  },
  iconWrap: {
    width: 104,
    height: 104,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.border,
  },
  title: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
    textAlign: "center",
  },
  body: {
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 24,
  },
  savingText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.muted },
  actions: { padding: sizes.screenPadding, gap: spacing.md },
});
