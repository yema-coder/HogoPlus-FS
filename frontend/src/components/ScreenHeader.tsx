import { useRouter, type Href } from "expo-router";
import { ArrowLeft } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors, fonts, sizes, spacing, type } from "@/src/theme/tokens";

interface Props {
  title: string;
  back?: boolean;
  right?: React.ReactNode;
  testID?: string;
  /** Deterministic back: onBack wins; else backTo (replace); else pop with home fallback. */
  onBack?: () => void;
  backTo?: Href;
}

/** Sticky, safe-area-aware screen header (72px content height). */
export function ScreenHeader({ title, back = true, right, testID = "screen-header", onBack, backTo }: Props) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const goBack = () => {
    if (onBack) {
      onBack();
      return;
    }
    if (backTo) {
      router.replace(backTo);
      return;
    }
    if (router.canGoBack()) router.back();
    else router.replace("/(tabs)/home");
  };
  return (
    <View style={[styles.wrap, { paddingTop: insets.top }]} testID={testID}>
      <View style={styles.row}>
        {back ? (
          <Pressable
            testID={`${testID}-back-button`}
            accessibilityRole="button"
            onPress={goBack}
            style={styles.backBtn}
          >
            <ArrowLeft size={26} color={colors.text} strokeWidth={2.4} />
          </Pressable>
        ) : (
          <View style={styles.backBtn} />
        )}
        <Text style={styles.title} numberOfLines={1}>
          {title}
        </Text>
        <View style={styles.right}>{right}</View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.background,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    zIndex: 10,
  },
  row: {
    height: sizes.headerHeight,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
  },
  backBtn: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    flex: 1,
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
  },
  right: {
    minWidth: sizes.touchTarget,
    alignItems: "flex-end",
    justifyContent: "center",
    paddingRight: spacing.sm,
  },
});
