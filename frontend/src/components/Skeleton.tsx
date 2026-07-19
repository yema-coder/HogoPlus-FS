import React, { useEffect, useRef } from "react";
import { Animated, StyleSheet, View } from "react-native";

import { colors, radius, spacing } from "@/src/theme/tokens";

/** Lightweight pulsing skeleton rows — shown instead of a blank wait when no cache exists. */
export function SkeletonRows({ rows = 5, height = 72 }: { rows?: number; height?: number }) {
  const pulse = useRef(new Animated.Value(0.4)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.4, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  return (
    <View style={styles.wrap} testID="skeleton-rows">
      {Array.from({ length: rows }).map((_, i) => (
        <Animated.View key={i} style={[styles.row, { height, opacity: pulse }]}>
          <View style={styles.circle} />
          <View style={{ flex: 1, gap: 8 }}>
            <View style={[styles.bar, { width: "70%" }]} />
            <View style={[styles.bar, { width: "45%" }]} />
          </View>
        </Animated.View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.md },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
  },
  circle: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surfaceTertiary },
  bar: { height: 12, borderRadius: 6, backgroundColor: colors.surfaceTertiary },
});
