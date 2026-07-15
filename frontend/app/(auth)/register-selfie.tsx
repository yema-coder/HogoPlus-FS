import * as ImageManipulator from "expo-image-manipulator";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useState } from "react";
import { StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "@/src/api/client";
import { registerEmployee } from "@/src/api/endpoints";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { SelfieCamera } from "@/src/components/SelfieCamera";
import { showToast } from "@/src/components/Toast";
import { useAuthStore } from "@/src/stores/authStore";
import { colors } from "@/src/theme/tokens";

export default function RegisterSelfie() {
  const router = useRouter();
  const { t } = useTranslation();
  const { name } = useLocalSearchParams<{ name: string }>();
  const [busy, setBusy] = useState(false);
  const registrationToken = useAuthStore((s) => s.registrationToken);
  const pendingPhone = useAuthStore((s) => s.pendingPhone);
  const setSession = useAuthStore((s) => s.setSession);

  const finish = async (uri: string) => {
    if (!registrationToken || !pendingPhone || !name) {
      showToast(t("errors.sessionExpired"), "error");
      router.replace("/(auth)/phone");
      return;
    }
    setBusy(true);
    try {
      const compressed = await ImageManipulator.manipulateAsync(
        uri,
        [{ resize: { width: 720 } }],
        { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG },
      );
      const uploaded = await uploadFile(compressed.uri, "selfie.jpg", registrationToken);
      const res = await registerEmployee(
        {
          phone: pendingPhone,
          full_name: name,
          selfie_key: uploaded.key,
        },
        registrationToken,
      );
      await setSession(
        { access_token: res.access_token, refresh_token: res.refresh_token },
        res.employee,
      );
      router.replace("/(auth)/pending");
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else if (e instanceof ApiError && e.status === 401) {
        showToast(t("errors.sessionExpired"), "error");
        router.replace("/(auth)/phone");
      } else showToast(t("errors.server"), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="register-selfie-screen">
      <ScreenHeader title={t("reg.selfieTitle")} />
      <SelfieCamera
        hint={t("reg.selfieHint")}
        onUse={(uri) => void finish(uri)}
        onClose={() => (router.canGoBack() ? router.back() : router.replace("/(auth)/phone"))}
        busy={busy}
        busyLabel={t("reg.creating")}
        testIDPrefix="register-selfie"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
});
