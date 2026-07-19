import { Image, StyleSheet, Text, View } from "react-native";
import React from "react";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { fonts } from "@/src/theme/tokens";

export const BRAND_MAROON = "#7A1F2B";

/** Slim maroon brand band for screens WITHOUT the bottom tab bar. Safe-area aware. */
export function BrandFooter() {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.band, { paddingBottom: insets.bottom }]} testID="brand-footer">
      <View style={styles.inner}>
        <View style={styles.logoChip}>
          <Image
            source={require("@/assets/images/logo.png")}
            style={styles.logo}
            resizeMode="contain"
          />
        </View>
        <Text style={styles.text}>HogoPlus-FS</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  band: { backgroundColor: BRAND_MAROON },
  inner: {
    height: 36,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  logoChip: {
    backgroundColor: "#FFFFFF",
    borderRadius: 6,
    paddingHorizontal: 3,
    paddingVertical: 2,
  },
  logo: { width: 18, height: 15 },
  text: { fontFamily: fonts.bold, fontSize: 12, color: "#FFFFFF", letterSpacing: 0.5 },
});
