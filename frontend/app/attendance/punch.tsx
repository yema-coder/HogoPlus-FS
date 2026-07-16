import * as ImageManipulator from "expo-image-manipulator";
import { useRouter } from "expo-router";
import { Check, X } from "lucide-react-native";
import React, { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "@/src/api/client";
import { beaconMacs, punchIn } from "@/src/api/endpoints";
import type { AttendanceRecord } from "@/src/api/types";
import { EyeLoader } from "@/src/components/EyeLoader";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { SelfieCamera } from "@/src/components/SelfieCamera";
import { showToast } from "@/src/components/Toast";
import { getBleScanner, ensureBlePermissions } from "@/src/ble/BleScanner";
import { useOutboxStore } from "@/src/offline/outbox";
import { colors, fonts, sizes, spacing, type } from "@/src/theme/tokens";
import { acquireGps } from "@/src/utils/gps";
import { reverseGeocode } from "@/src/utils/geocode";
import { storage } from "@/src/utils/storage";

type StepState = "pending" | "running" | "ok" | "skip";

interface Steps {
  gps: StepState;
  zone: StepState;
  upload: StepState;
}

/** Punch-in: selfie → GPS → BLE zone → upload. Degrades gracefully offline. */
export default function PunchInScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const enqueue = useOutboxStore((s) => s.enqueue);
  const [steps, setSteps] = useState<Steps | null>(null);

  const setStep = (key: keyof Steps, state: StepState) =>
    setSteps((prev) => (prev ? { ...prev, [key]: state } : prev));

  const run = async (uri: string) => {
    setSteps({ gps: "running", zone: "pending", upload: "pending" });

    const { fix } = await acquireGps(8000);
    setStep("gps", fix ? "ok" : "skip");
    const address = fix ? await reverseGeocode(fix.lat, fix.lng) : null;

    setStep("zone", "running");
    let ble = null;
    try {
      const scanner = getBleScanner();
      if (scanner.isReal) {
        let macs: string[] = [];
        try {
          macs = (await beaconMacs()).macs;
        } catch {
          macs = []; // offline / endpoint failure → skip zone step gracefully
        }
        const asked = await storage.getItem<boolean>("hogo.bleAsked", false);
        if (!asked) {
          showToast(t("perm.bleExplain"), "info");
          await storage.setItem("hogo.bleAsked", true);
        }
        const allowed = await ensureBlePermissions();
        ble = allowed ? await scanner.scan(3000, macs) : null;
      } else {
        ble = await scanner.scan(3000, []);
      }
    } catch {
      ble = null;
    }
    setStep("zone", ble ? "ok" : "skip");

    setStep("upload", "running");
    const payload: Record<string, unknown> = {
      gps_lat: fix?.lat ?? null,
      gps_lng: fix?.lng ?? null,
      ble_beacon_id: ble?.mac ?? null,
    };

    let selfieUri = uri;
    try {
      const compressed = await ImageManipulator.manipulateAsync(
        uri,
        [{ resize: { width: 720 } }],
        { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG },
      );
      selfieUri = compressed.uri;
    } catch {
      // upload original if compression fails
    }

    try {
      const uploaded = await uploadFile(selfieUri, "selfie.jpg");
      const record = (await punchIn({ ...payload, selfie_key: uploaded.key })) as AttendanceRecord;
      setStep("upload", "ok");
      router.replace({
        pathname: "/attendance/result",
        params: {
          queued: "0",
          level: record.verification_level,
          zone: record.ble_zone ?? "",
          late: record.is_late ? "1" : "0",
          time: record.punch_in_at ?? "",
          addr: address ?? "",
          coords: fix ? `${fix.lat.toFixed(5)}, ${fix.lng.toFixed(5)}` : "",
        },
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        showToast(t("att.already"), "error");
        router.replace("/(tabs)/home");
      } else if (e instanceof ApiError && e.status === 0) {
        await enqueue({
          type: "attendance",
          payload,
          photoUri: selfieUri,
          photoName: "selfie.jpg",
          photoField: "selfie_key",
        });
        router.replace({ pathname: "/attendance/result", params: { queued: "1", level: "", zone: "", late: "0", time: "" } });
      } else if (e instanceof ApiError && (e.status === 400 || e.status === 413)) {
        const extra = typeof e.detail === "string" ? ` (${e.detail})` : "";
        showToast(`${t("errors.uploadRejected")}${extra}`, "error");
        setSteps(null);
      } else {
        showToast(t("errors.server"), "error");
        setSteps(null);
      }
    }
  };

  const stepIcon = (state: StepState) => {
    if (state === "running") return <EyeLoader size={16} />;
    if (state === "ok") return <Check size={22} color={colors.success} strokeWidth={3} />;
    if (state === "skip") return <X size={22} color={colors.warning} strokeWidth={3} />;
    return <View style={styles.pendingDot} />;
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="punch-in-screen">
      <ScreenHeader title={t("att.punchIn")} />
      {steps ? (
        <View style={styles.stepsWrap} testID="punch-in-steps">
          {(
            [
              { key: "gps" as const, label: t("att.checking") },
              { key: "zone" as const, label: t("att.zoneChecking") },
              { key: "upload" as const, label: t("att.uploading") },
            ]
          ).map((s) => (
            <View key={s.key} style={styles.stepRow} testID={`punch-step-${s.key}`}>
              <View style={styles.stepIcon}>{stepIcon(steps[s.key])}</View>
              <Text style={styles.stepLabel}>{s.label}</Text>
            </View>
          ))}
          <Text style={styles.hint}>
            {steps.gps === "skip" ? t("perm.gpsOffNote") : t("att.locationPermissionBody")}
          </Text>
        </View>
      ) : (
        <SelfieCamera
          hint={t("att.faceGuide")}
          onUse={(uri) => void run(uri)}
          onClose={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/home"))}
          testIDPrefix="punch-selfie"
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  stepsWrap: {
    flex: 1,
    justifyContent: "center",
    padding: sizes.screenPadding,
    gap: spacing.xl,
  },
  stepRow: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  stepIcon: { width: 32, alignItems: "center" },
  stepLabel: { fontFamily: fonts.semiBold, fontSize: type.lg, color: colors.text },
  pendingDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.border,
  },
  hint: {
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.xl,
  },
});
