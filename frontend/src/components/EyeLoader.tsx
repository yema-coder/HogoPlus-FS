import React, { useEffect, useRef } from "react";
import { Animated, AppState, Easing, Image, StyleSheet } from "react-native";

// Real logo layers (user-supplied, pre-separated):
// base 502×408 — full logo with the iris socket filled white; iris 202×202 — eyeball only.
const BASE = require("@/assets/images/eye-base.png");
const IRIS = require("@/assets/images/eye-iris.png");

const RATIO = 502 / 408; // base width / height
const IRIS_CX = 0.514; // iris centre, fraction of base width
const IRIS_CY = 0.547; // iris centre, fraction of base height
const IRIS_D = 0.4; // iris diameter, fraction of base width
const TRAVEL = 0.12; // max iris travel each side, fraction of base width (stays inside the white opening)

interface Props {
  /** Logo height in px — width is ~1.23×. Defaults to 40 (full-screen loader). */
  size?: number;
  testID?: string;
}

/**
 * Brand eye loader — the REAL app logo, animated as two layers.
 * ~2s loop: iris looks LEFT → hold 250ms → RIGHT → hold 250ms → centre →
 * BLINK (whole logo scaleY → 0.08 and back, ~200ms) → repeat.
 * Native-driver transforms only; pauses while the app is backgrounded.
 */
export function EyeLoader({ size = 40, testID = "eye-loader" }: Props) {
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
          Animated.delay(250), // hold
          timing(iris, 1, 460), // look right
          Animated.delay(250), // hold
          timing(iris, 0, 280), // back to centre
          Animated.delay(120),
          timing(lid, 0.08, 100), // blink close
          timing(lid, 1, 100), // blink open
          Animated.delay(200),
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

  const h = size;
  const w = size * RATIO;
  const irisD = w * IRIS_D;
  const maxX = w * TRAVEL;

  return (
    <Animated.View testID={testID} style={{ width: w, height: h, transform: [{ scaleY: lid }] }}>
      <Image source={BASE} style={styles.base} resizeMode="contain" />
      <Animated.View
        style={{
          position: "absolute",
          width: irisD,
          height: irisD,
          left: w * IRIS_CX - irisD / 2,
          top: h * IRIS_CY - irisD / 2,
          transform: [
            { translateX: iris.interpolate({ inputRange: [-1, 1], outputRange: [-maxX, maxX] }) },
          ],
        }}
      >
        <Image source={IRIS} resizeMode="contain" style={styles.iris} />
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  base: { ...StyleSheet.absoluteFillObject, width: "100%", height: "100%" },
  iris: { width: "100%", height: "100%" },
});
