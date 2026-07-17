import { Redirect } from "expo-router";
import React from "react";
import { Platform, StyleSheet, Text, View } from "react-native";

import { EyeLoader } from "@/src/components/EyeLoader";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, type } from "@/src/theme/tokens";

export default function Index() {
  const { status, profile, langPicked, permsPrimed } = useAuthStore();

  if (status === "loading") {
    return (
      <View style={styles.splash} testID="splash-screen">
        <Text style={styles.logo}>HogoPlus-FS</Text>
        <EyeLoader size={36} />
      </View>
    );
  }
  if (!langPicked && status !== "authenticated") return <Redirect href="/(auth)/language" />;
  if (status !== "authenticated") return <Redirect href="/(auth)/phone" />;
  if (profile && profile.onboarding_status !== "approved") return <Redirect href="/(auth)/pending" />;
  if (Platform.OS !== "web" && !permsPrimed) return <Redirect href="/permissions" />;
  return <Redirect href="/(tabs)/home" />;
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    gap: 24,
  },
  logo: {
    fontFamily: fonts.bold,
    fontSize: type.xxl,
    color: colors.onPrimary,
  },
});
