// Presentational overlay for the AR object-distance feature. Crosshair at the
// measured point + a FIXED top banner for the live distance (kept well clear of
// the bottom photo/video shutter controls — A3). Optional admin/dev debug HUD
// (active tier, tracking, samples, spread, confidence) with a calibrate shortcut.
// Pure UI — all state is owned by DistanceCamera / the screen.

import { Flashlight, FlashlightOff, Ruler } from "lucide-react-native";
import React, { useRef } from "react";
import { LayoutChangeEvent, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { formatDistance } from "@/src/ar/distanceFilter";
import { getCalibrationSync } from "@/src/ar/calibration";
import { tapToViewFraction, type Rect } from "@/src/ar/tapMapping";
import type { ArCapabilities, DistanceReading } from "@/src/ar/types";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

interface Props {
  reading: DistanceReading | null;
  caps: ArCapabilities | null;
  target: { x: number; y: number }; // fractions 0..1
  torchOn: boolean;
  onTapMeasure: (xFrac: number, yFrac: number) => void;
  onToggleTorch: () => void;
  /** admin/dev only — shows the diagnostic HUD + calibrate shortcut */
  debug?: boolean;
  onCalibrate?: () => void;
}

const confColor = (r: DistanceReading) =>
  r.confidence === "high" ? colors.success : r.confidence === "medium" ? colors.warning : colors.muted;

export function ArDistanceOverlay({
  reading,
  caps,
  target,
  torchOn,
  onTapMeasure,
  onToggleTorch,
  debug = false,
  onCalibrate,
}: Props) {
  const { t } = useTranslation();
  const insets = useSafeAreaInsets();
  // The AR PREVIEW's own measured frame — the single reference every fraction is
  // expressed against (crosshair position AND the native depth target). Window
  // dimensions are deliberately never used: the preview is not always the window.
  const viewSize = useRef({ w: 0, h: 0 });
  // The touch layer's frame INSIDE that preview (it stops above the shutter), so
  // a touch reported in layer-local coordinates can be put back where it belongs.
  const tapLayer = useRef<Rect>({ x: 0, y: 0, w: 0, h: 0 });

  // AR genuinely unavailable in this runtime → tell the user plainly, once.
  const arOff = caps ? !caps.supported : false;
  const offMsg =
    caps?.reason === "no_native"
      ? t("ar.needsBuild")
      : caps?.reason === "no_arcore"
        ? t("ar.installArcore")
        : t("ar.notSupported");

  const onViewLayout = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    viewSize.current = { w: width, h: height };
  };

  const onTapLayerLayout = (e: LayoutChangeEvent) => {
    const { x, y, width, height } = e.nativeEvent.layout;
    tapLayer.current = { x, y, w: width, h: height };
  };

  const handlePress = (e: { nativeEvent: { locationX: number; locationY: number } }) => {
    // locationX/Y are relative to the TOUCH LAYER; the fraction must be relative
    // to the AR PREVIEW. Mixing the two is what put the crosshair (and the depth
    // sample) ~1.4x too far down the screen — see src/ar/tapMapping.ts.
    const frac = tapToViewFraction(
      e.nativeEvent.locationX,
      e.nativeEvent.locationY,
      tapLayer.current,
      viewSize.current,
    );
    if (!frac) return; // not measured yet — never guess a target
    onTapMeasure(frac.x, frac.y);
  };

  const distText = reading ? formatDistance(reading) : "";
  const hintText = reading?.hint ? t(`ar.hint.${reading.hint}`) : "";
  const bannerTop = insets.top + 64; // below the close / GPS chip row
  const cal = getCalibrationSync();

  return (
    <View style={styles.fill} pointerEvents="box-none" onLayout={onViewLayout}>
      {/* tap-to-measure layer (upper region only, so the shutter stays tappable).
          Its frame is measured separately from the preview frame above — the two
          are NOT the same rectangle, and conflating them was the A1 field bug. */}
      <Pressable style={styles.tapLayer} onPress={handlePress} onLayout={onTapLayerLayout} />

      {/* fixed distance banner — always clear of the bottom controls */}
      {!arOff ? (
        <View pointerEvents="none" style={[styles.banner, { top: bannerTop }]}>
          {distText ? (
            <View style={[styles.bannerPill, { backgroundColor: confColor(reading!) }]} testID="ar-distance-pill">
              <Ruler size={16} color="#FFFFFF" strokeWidth={2.4} />
              <Text style={styles.bannerText}>{distText}</Text>
            </View>
          ) : hintText ? (
            <View style={[styles.bannerPill, styles.hintPill]} testID="ar-distance-hint">
              <Text style={styles.hintText}>{hintText}</Text>
            </View>
          ) : (
            <View style={[styles.bannerPill, styles.hintPill]} testID="ar-distance-measuring">
              <Text style={styles.hintText}>{t("ar.measuring")}</Text>
            </View>
          )}
        </View>
      ) : (
        <View style={[styles.banner, { top: bannerTop }]} pointerEvents="none">
          <View style={styles.offChip} testID="ar-distance-off">
            <Text style={styles.offText}>📏 {offMsg}</Text>
          </View>
        </View>
      )}

      {/* crosshair reticle at the measured point (no number — it lives in the banner) */}
      {!arOff ? (
        <View
          pointerEvents="none"
          style={[styles.crosshairWrap, { left: `${target.x * 100}%`, top: `${target.y * 100}%` }]}
        >
          <View style={styles.crosshairV} />
          <View style={styles.crosshairH} />
          <View style={[styles.crosshairDot, reading?.show ? { backgroundColor: confColor(reading) } : null]} />
        </View>
      ) : null}

      {/* admin/dev reprojection dot — the native back-projected position of the
          EXACT point we sampled; if it sits on the crosshair, the tap→depth
          mapping is landing under the finger (A1 verification). */}
      {debug && !arOff && reading?.projX != null && reading?.projY != null ? (
        <View
          pointerEvents="none"
          style={[styles.reproj, { left: `${reading.projX * 100}%`, top: `${reading.projY * 100}%` }]}
          testID="ar-reproj-dot"
        >
          <View style={styles.reprojRing} />
        </View>
      ) : null}

      {/* admin/dev diagnostic HUD */}
      {debug && !arOff ? (
        <View style={[styles.hud, { top: bannerTop + 44 }]} pointerEvents="box-none" testID="ar-debug-hud">
          <Text style={styles.hudTitle}>{t("ar.hud.title")}</Text>
          <Text style={styles.hudLine}>
            {t("ar.hud.tier")}: {reading?.method ?? "none"}
          </Text>
          <Text style={styles.hudLine}>
            {t("ar.hud.tracking")}: {reading?.trackingState ?? "—"}
          </Text>
          <Text style={styles.hudLine}>
            {t("ar.hud.samples")}: {reading?.sampleCount ?? 0} · {t("ar.hud.spread")}: ±
            {(reading?.spread ?? 0).toFixed(2)}
          </Text>
          <Text style={styles.hudLine}>
            {t("ar.hud.confidence")}: {reading?.confidence ?? "—"}
          </Text>
          <Text style={styles.hudLine}>
            {t("ar.hud.reproj")}:{" "}
            {reading?.projX != null && reading?.projY != null
              ? `${reading.projX.toFixed(2)}, ${reading.projY.toFixed(2)}`
              : "—"}
          </Text>
          {/* the tap fraction actually sent to the native layer — compare it with
              the reprojection line above and with where your finger landed */}
          <Text style={styles.hudLine}>
            {t("ar.hud.target")}: {target.x.toFixed(2)}, {target.y.toFixed(2)}
          </Text>
          <Text style={styles.hudLine}>
            {t("ar.hud.converged")}: {reading?.converged ? "yes" : "no"}
          </Text>
          {cal.scale !== 1 ? (
            <Text style={styles.hudCal}>{t("ar.hud.calibrated", { s: cal.scale.toFixed(3) })}</Text>
          ) : null}
          <Pressable
            testID="ar-calibrate-button"
            accessibilityRole="button"
            onPress={onCalibrate}
            style={({ pressed }) => [styles.hudBtn, pressed && { opacity: 0.7 }]}
          >
            <Text style={styles.hudBtnText}>{t("ar.hud.calibrate")}</Text>
          </Pressable>
        </View>
      ) : null}

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
  banner: { position: "absolute", left: 0, right: 0, alignItems: "center" },
  bannerPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: 6,
    minWidth: 96,
    justifyContent: "center",
  },
  bannerText: { fontFamily: fonts.bold, fontSize: type.lg, color: "#FFFFFF" },
  hintPill: { backgroundColor: "rgba(0,0,0,0.6)" },
  hintText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
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
  reproj: { position: "absolute", width: 28, height: 28, marginLeft: -14, marginTop: -14, alignItems: "center", justifyContent: "center" },
  reprojRing: { width: 26, height: 26, borderRadius: 13, borderWidth: 2, borderColor: "#FF3DCB", backgroundColor: "transparent" },
  offChip: {
    backgroundColor: "rgba(0,0,0,0.6)",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  offText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
  hud: {
    position: "absolute",
    left: spacing.md,
    backgroundColor: "rgba(0,0,0,0.62)",
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: 2,
    maxWidth: 220,
  },
  hudTitle: { fontFamily: fonts.bold, fontSize: 12, color: "#8EE3FF", marginBottom: 2 },
  hudLine: { fontFamily: fonts.medium, fontSize: 12, color: "#FFFFFF" },
  hudCal: { fontFamily: fonts.semiBold, fontSize: 12, color: "#FFD54A", marginTop: 2 },
  hudBtn: {
    marginTop: spacing.xs,
    alignSelf: "flex-start",
    borderWidth: 1.5,
    borderColor: "#8EE3FF",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
  },
  hudBtnText: { fontFamily: fonts.bold, fontSize: 12, color: "#8EE3FF" },
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
