// Admin tape-measure calibration for the AR distance feature (A3). Aim at an
// object at a KNOWN distance (measured with a tape), enter that distance, and
// record a few samples. The median truth/measured ratio becomes a persistent
// correction factor applied to every live reading + captured measurement.
// Admin/dev only. Device-only (needs the native AR build to produce readings).

import { useCameraPermissions } from "expo-camera";
import { useRouter } from "expo-router";
import { Camera as CameraIcon, Settings, Trash2 } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { Linking, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { DistanceCamera, type DistanceCameraRef } from "@/src/ar/DistanceCamera";
import {
  computeScale,
  getCalibrationSync,
  loadCalibration,
  resetCalibration,
  saveCalibration,
  type ArCalibration,
} from "@/src/ar/calibration";
import type { ArCapabilities, DistanceReading } from "@/src/ar/types";
import { ArDistanceOverlay } from "@/src/components/ArDistanceOverlay";
import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

interface Pair {
  measured: number; // raw (un-calibrated) AR reading
  truth: number; // tape-measured ground truth
}

export default function ArCalibrationScreen() {
  const { t } = useTranslation();
  const router = useRouter();
  const profile = useAuthStore((s) => s.profile);
  const rank = profile?.role?.rank ?? 6;
  const isAdmin = rank <= 2;

  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = React.useRef<DistanceCameraRef>(null);
  const [reading, setReading] = useState<DistanceReading | null>(null);
  const [caps, setCaps] = useState<ArCapabilities | null>(null);
  const [torch, setTorch] = useState(false);
  const [target, setTarget] = useState({ x: 0.5, y: 0.5 });
  const [truth, setTruth] = useState("");
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [cal, setCal] = useState<ArCalibration>(getCalibrationSync());

  useEffect(() => {
    void loadCalibration().then(setCal);
  }, []);

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]} testID="ar-calibration-screen">
        <ScreenHeader title={t("ar.calib.title")} />
        <View style={styles.center} testID="ar-calib-denied">
          <Text style={styles.deniedText}>{t("ar.calib.adminOnly")}</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!permission) return <View style={styles.safe} />;

  if (!permission.granted) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]} testID="ar-calibration-screen">
        <ScreenHeader title={t("ar.calib.title")} />
        <View style={styles.center}>
          <Text style={styles.introText}>{t("incident.cameraPermissionBody")}</Text>
          {permission.canAskAgain ? (
            <BigButton
              testID="ar-calib-grant-camera"
              label={t("incident.cameraPermissionTitle")}
              icon={CameraIcon}
              onPress={() => void requestPermission()}
            />
          ) : (
            <BigButton
              testID="ar-calib-open-settings"
              label={t("common.openSettings")}
              icon={Settings}
              variant="outline"
              onPress={() => void Linking.openSettings()}
            />
          )}
        </View>
      </SafeAreaView>
    );
  }

  const measured = reading?.distanceM != null ? reading.distanceM / (cal.scale || 1) : null;
  const previewScale = computeScale(pairs);

  const record = () => {
    const live = cameraRef.current?.getLastReading() ?? reading;
    const rawMeasured = live?.distanceM != null ? live.distanceM / (cal.scale || 1) : null;
    const tv = parseFloat(truth.replace(",", "."));
    if (rawMeasured == null) {
      showToast(t("ar.calib.needReading"), "error");
      return;
    }
    if (!Number.isFinite(tv) || tv <= 0) {
      showToast(t("ar.calib.needTruth"), "error");
      return;
    }
    setPairs((p) => [...p, { measured: Math.round(rawMeasured * 100) / 100, truth: tv }]);
    showToast(t("common.done"), "success");
  };

  const save = async () => {
    if (pairs.length === 0) {
      showToast(t("ar.calib.needReading"), "error");
      return;
    }
    const next = await saveCalibration(computeScale(pairs), pairs.length);
    setCal(next);
    showToast(t("ar.calib.saved"), "success");
  };

  const reset = async () => {
    await resetCalibration();
    setPairs([]);
    setCal(getCalibrationSync());
    showToast(t("common.done"), "success");
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="ar-calibration-screen">
      <ScreenHeader title={t("ar.calib.title")} onBack={() => router.back()} />
      <View style={styles.cameraArea}>
        <DistanceCamera
          ref={cameraRef}
          style={StyleSheet.absoluteFill}
          facing="back"
          mode="picture"
          enableTorch={torch}
          active
          onReading={setReading}
          onCapabilities={setCaps}
        />
        <ArDistanceOverlay
          reading={reading}
          caps={caps}
          target={target}
          torchOn={torch}
          debug
          onTapMeasure={(x, y) => {
            setTarget({ x, y });
            cameraRef.current?.setTarget(x, y);
          }}
          onToggleTorch={() => setTorch((v) => !v)}
        />
      </View>

      <ScrollView contentContainerStyle={styles.panel} keyboardShouldPersistTaps="handled">
        <Text style={styles.intro}>{t("ar.calib.intro")}</Text>

        <View style={styles.readingRow}>
          <Text style={styles.readingLabel}>{t("ar.calib.current")}</Text>
          <Text style={styles.readingValue} testID="ar-calib-live">
            {measured != null ? `${measured.toFixed(2)} m` : "—"}
          </Text>
        </View>

        <Text style={styles.fieldLabel}>{t("ar.calib.trueDistance")}</Text>
        <View style={styles.inputRow}>
          <TextInput
            testID="ar-calib-truth-input"
            style={styles.input}
            value={truth}
            onChangeText={setTruth}
            keyboardType="decimal-pad"
            placeholder="2.50"
            placeholderTextColor={colors.muted}
          />
          <BigButton
            testID="ar-calib-record"
            label={t("ar.calib.record")}
            onPress={record}
            style={{ flex: 1 }}
          />
        </View>

        {pairs.length > 0 ? (
          <View style={styles.samples} testID="ar-calib-samples">
            {pairs.map((p, i) => (
              <View key={i} style={styles.sampleRow}>
                <Text style={styles.sampleText}>
                  {p.measured.toFixed(2)} m → {p.truth.toFixed(2)} m (×{(p.truth / p.measured).toFixed(3)})
                </Text>
                <Pressable
                  testID={`ar-calib-del-${i}`}
                  onPress={() => setPairs((prev) => prev.filter((_, j) => j !== i))}
                  hitSlop={8}
                >
                  <Trash2 size={16} color={colors.danger} strokeWidth={2.2} />
                </Pressable>
              </View>
            ))}
            <Text style={styles.scalePreview} testID="ar-calib-scale">
              {t("ar.calib.scale")}: ×{previewScale.toFixed(3)} ({pairs.length})
            </Text>
          </View>
        ) : null}

        <View style={styles.actions}>
          <BigButton
            testID="ar-calib-save"
            label={t("ar.calib.save")}
            variant="success"
            disabled={pairs.length === 0}
            onPress={() => void save()}
            style={{ flex: 2 }}
          />
          <BigButton
            testID="ar-calib-reset"
            label={t("ar.calib.reset")}
            variant="muted"
            onPress={() => void reset()}
            style={{ flex: 1 }}
          />
        </View>

        <Text style={styles.savedNote} testID="ar-calib-saved-note">
          {cal.scale !== 1
            ? t("ar.hud.calibrated", { s: cal.scale.toFixed(3) })
            : t("ar.calib.none")}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: sizes.screenPadding, gap: spacing.lg },
  deniedText: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.muted, textAlign: "center" },
  introText: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted, textAlign: "center" },
  cameraArea: { height: "44%", backgroundColor: "#000000", overflow: "hidden" },
  panel: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.xxl },
  intro: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  readingRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  readingLabel: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  readingValue: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.primary },
  fieldLabel: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  inputRow: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  input: {
    flex: 1,
    height: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    fontFamily: fonts.bold,
    fontSize: type.lg,
    color: colors.text,
  },
  samples: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  sampleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sampleText: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.text },
  scalePreview: { fontFamily: fonts.bold, fontSize: type.base, color: colors.primary, marginTop: spacing.xs },
  actions: { flexDirection: "row", gap: spacing.md },
  savedNote: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted, textAlign: "center" },
});
