import { Redirect } from "expo-router";
import React from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, type } from "@/src/theme/tokens";

export default function Index() {
  const { status, profile, langPicked } = useAuthStore();

  if (status === "loading") {
    return (
      <View style={styles.splash} testID="splash-screen">
        <Text style={styles.logo}>Hogo Plus</Text>
        <ActivityIndicator size="large" color={colors.onPrimary} />
      </View>
    );
  }
  if (!langPicked && status !== "authenticated") return <Redirect href="/(auth)/language" />;
  if (status !== "authenticated") return <Redirect href="/(auth)/phone" />;
  if (profile && profile.onboarding_status !== "approved") return <Redirect href="/(auth)/pending" />;
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
