// Presentational overlay for PART 1: crosshair at the measured point, live
// distance pill (coloured by confidence), one-line auto-fix hint, torch toggle,
// and tap-to-measure. Pure UI — all state is owned by DistanceCamera / the screen.

import { Flashlight, FlashlightOff } from "lucide-react-native";
import React, { useRef } from "react";
import { LayoutChangeEvent, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { formatDistance } from "@/src/ar/distanceFilter";
import type { ArCapabilities, DistanceReading } from "@/src/ar/types";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

interface Props {
  reading: DistanceReading | null;
  caps: ArCapabilities | null;
  target: { x: number; y: number }; // fractions 0..1
  torchOn: boolean;
  onTapMeasure: (xFrac: number, yFrac: number) => void;
  onToggleTorch: () => void;
}

const confColor = (r: DistanceReading) =>
  r.confidence === "high" ? colors.success : r.confidence === "medium" ? colors.warning : colors.muted;

export function ArDistanceOverlay({ reading, caps, target, torchOn, onTapMeasure, onToggleTorch }: Props) {
  const { t } = useTranslation();
  const size = useRef({ w: 0, h: 0 });

  // AR genuinely unavailable in this runtime → tell the user plainly, once.
  const arOff = caps ? !caps.supported : false;
  const offMsg =
    caps?.reason === "no_native"
      ? t("ar.needsBuild")
      : caps?.reason === "no_arcore"
        ? t("ar.installArcore")
        : t("ar.notSupported");

  const onLayout = (e: LayoutChangeEvent) => {
    size.current = { w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height };
  };

  const handlePress = (e: { nativeEvent: { locationX: number; locationY: number } }) => {
    const { w, h } = size.current;
    if (!w || !h) return;
    const x = Math.min(1, Math.max(0, e.nativeEvent.locationX / w));
    const y = Math.min(1, Math.max(0, e.nativeEvent.locationY / h));
    onTapMeasure(x, y);
  };

  const distText = reading ? formatDistance(reading) : "";
  const hintKey = reading?.hint;
  const hintText = hintKey ? t(`ar.hint.${hintKey}`) : "";

  return (
    <View style={styles.fill} pointerEvents="box-none">
      {/* tap-to-measure layer (upper region only, so the shutter stays tappable) */}
      <Pressable style={styles.tapLayer} onPress={handlePress} onLayout={onLayout} />

      {!arOff ? (
        <View
          pointerEvents="none"
          style={[styles.crosshairWrap, { left: `${target.x * 100}%`, top: `${target.y * 100}%` }]}
        >
          <View style={styles.crosshairV} />
          <View style={styles.crosshairH} />
          <View style={styles.crosshairDot} />
          {distText ? (
            <View style={[styles.pill, { backgroundColor: confColor(reading!) }]} testID="ar-distance-pill">
              <Text style={styles.pillText}>{distText}</Text>
            </View>
          ) : hintText ? (
            <View style={[styles.pill, styles.hintPill]} testID="ar-distance-hint">
              <Text style={styles.hintText}>{hintText}</Text>
            </View>
          ) : (
            <View style={[styles.pill, styles.hintPill]} testID="ar-distance-measuring">
              <Text style={styles.hintText}>{t("ar.measuring")}</Text>
            </View>
          )}
        </View>
      ) : (
        <View style={styles.offWrap} pointerEvents="none">
          <View style={styles.offChip} testID="ar-distance-off">
            <Text style={styles.offText}>📏 {offMsg}</Text>
          </View>
        </View>
      )}

      {/* torch toggle — auto-on in low light, user can switch it off */}
      {!arOff ? (
        <Pressable
          testID="ar-torch-toggle"
          accessibilityRole="button"
          accessibilityLabel={t("ar.torch")}
          onPress={onToggleTorch}
          style={styles.torchBtn}
        >
          {torchOn ? (
            <Flashlight size={22} color="#FFD54A" strokeWidth={2.4} />
          ) : (
            <FlashlightOff size={22} color="#FFFFFF" strokeWidth={2.4} />
          )}
        </Pressable>
      ) : null}
    </View>
  );
}

const CH = 44; // crosshair reticle size
const styles = StyleSheet.create({
  fill: { ...StyleSheet.absoluteFillObject },
  tapLayer: { position: "absolute", left: 0, right: 0, top: 0, bottom: "28%" },
  crosshairWrap: {
    position: "absolute",
    width: CH,
    height: CH,
    marginLeft: -CH / 2,
    marginTop: -CH / 2,
    alignItems: "center",
    justifyContent: "center",
  },
  crosshairV: { position: "absolute", width: 2, height: CH, backgroundColor: "rgba(255,255,255,0.9)" },
  crosshairH: { position: "absolute", width: CH, height: 2, backgroundColor: "rgba(255,255,255,0.9)" },
  crosshairDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: "rgba(255,255,255,0.95)" },
  pill: {
    position: "absolute",
    top: CH / 2 + 8,
    alignSelf: "center",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    minWidth: 64,
    alignItems: "center",
  },
  pillText: { fontFamily: fonts.bold, fontSize: type.base, color: "#FFFFFF" },
  hintPill: { backgroundColor: "rgba(0,0,0,0.6)" },
  hintText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
  offWrap: { position: "absolute", top: "42%", left: 0, right: 0, alignItems: "center" },
  offChip: {
    backgroundColor: "rgba(0,0,0,0.6)",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  offText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
  torchBtn: {
    position: "absolute",
    right: spacing.lg,
    top: "50%",
    marginTop: -24,
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center",
    justifyContent: "center",
  },
});
