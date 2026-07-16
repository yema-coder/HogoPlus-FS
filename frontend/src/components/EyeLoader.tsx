import React, { useEffect, useRef } from "react";
import { Animated, AppState, Easing, StyleSheet, View } from "react-native";

import { colors } from "@/src/theme/tokens";

interface Props {
  /** Eye height in px — width is ~1.7×. Defaults to 40 (full-screen loader). */
  size?: number;
  /** Outline + iris colour. Defaults to brand primary. */
  color?: string;
  testID?: string;
}

/**
 * Brand "eye" loader — replaces generic spinners app-wide.
 * Sequence: iris looks LEFT → hold → RIGHT → hold → centre → BLINK → repeat.
 * Native-driver transforms only; pauses while the app is backgrounded.
 */
export function EyeLoader({ size = 40, color = colors.primary, testID = "eye-loader" }: Props) {
  const iris = useRef(new Animated.Value(0)).current;
  const lid = useRef(new Animated.Value(1)).current;
  const loop = useRef<Animated.CompositeAnimation | null>(null);

  useEffect(() => {
    const timing = (v: Animated.Value, toValue: number, duration: number) =>
      Animated.timing(v, {
        toValue,
        duration,
        easing: Easing.inOut(Easing.quad),
        useNativeDriver: true,
      });
    const start = () => {
      loop.current?.stop();
      iris.setValue(0);
      lid.setValue(1);
      loop.current = Animated.loop(
        Animated.sequence([
          timing(iris, -1, 280), // look left
          Animated.delay(340), // hold
          timing(iris, 1, 460), // look right
          Animated.delay(340), // hold
          timing(iris, 0, 280), // back to centre
          Animated.delay(160),
          timing(lid, 0.08, 90), // blink close
          timing(lid, 1, 140), // blink open
          Animated.delay(220),
        ]),
      );
      loop.current.start();
    };
    start();
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") start();
      else loop.current?.stop();
    });
    return () => {
      sub.remove();
      loop.current?.stop();
    };
  }, [iris, lid]);

  const w = Math.round(size * 1.7);
  const border = Math.max(2, Math.round(size * 0.09));
  const irisSize = Math.round(size * 0.52);
  const maxX = (w - irisSize) / 2 - border - Math.max(2, size * 0.08);

  return (
    <Animated.View testID={testID} style={{ width: w, height: size, transform: [{ scaleY: lid }] }}>
      <View
        style={[
          styles.outline,
          { borderRadius: size / 2, borderWidth: border, borderColor: color },
        ]}
      />
      <View style={styles.irisWrap}>
        <Animated.View
          style={{
            width: irisSize,
            height: irisSize,
            borderRadius: irisSize / 2,
            backgroundColor: color,
            transform: [
              { translateX: iris.interpolate({ inputRange: [-1, 1], outputRange: [-maxX, maxX] }) },
            ],
          }}
        >
          <View
            style={[
              styles.glint,
              {
                width: Math.max(3, Math.round(irisSize * 0.3)),
                height: Math.max(3, Math.round(irisSize * 0.3)),
                borderRadius: irisSize,
                top: Math.round(irisSize * 0.14),
                right: Math.round(irisSize * 0.14),
              },
            ]}
          />
        </Animated.View>
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  outline: { ...StyleSheet.absoluteFillObject },
  irisWrap: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  glint: { position: "absolute", backgroundColor: "rgba(255,255,255,0.85)" },
});
