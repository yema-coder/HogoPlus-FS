import * as ImageManipulator from "expo-image-manipulator";
import { useRouter } from "expo-router";
import { Check, X } from "lucide-react-native";
import React, { useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "@/src/api/client";
import { attachBeacon, punchIn } from "@/src/api/endpoints";
import type { AttendanceRecord } from "@/src/api/types";
import { EyeLoader } from "@/src/components/EyeLoader";
import { CaptureGuards } from "@/src/components/CaptureGuards";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { SelfieCamera } from "@/src/components/SelfieCamera";
import { showToast } from "@/src/components/Toast";
import { beaconPayload } from "@/src/ble/BleScanner";
import { startZoneSession, type ZoneSession } from "@/src/ble/zoneSession";
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
  // Prompt 17 Part D: camera/location/GPS/Bluetooth guards before the selfie
  return (
    <CaptureGuards camera location gps bluetooth strict>
      <PunchInInner />
    </CaptureGuards>
  );
}

function PunchInInner() {
  const router = useRouter();
  const { t } = useTranslation();
  const enqueue = useOutboxStore((s) => s.enqueue);
  const [steps, setSteps] = useState<Steps | null>(null);
  // v1.0.17 SPEED PACK: pre-warm the zone scan the moment the screen opens so it runs
  // in PARALLEL with the selfie — not sequentially after it (v1.0.16 field timing: ~1 min).
  const sessionRef = useRef<ZoneSession | null>(null);
  useEffect(() => {
    void (async () => {
      const asked = await storage.getItem<boolean>("hogo.bleAsked", false);
      if (!asked) {
        showToast(t("perm.bleExplain"), "info");
        await storage.setItem("hogo.bleAsked", true);
      }
      sessionRef.current = startZoneSession();
    })();
    // The session is NOT stopped on unmount: it self-terminates (≤60s) and powers the
    // post-submit late-attach upgrade when a match lands after the punch is stored.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setStep = (key: keyof Steps, state: StepState) =>
    setSteps((prev) => (prev ? { ...prev, [key]: state } : prev));

  const run = async (uri: string) => {
    const T: Record<string, number | string> = {};
    const t0 = Date.now();
    setSteps({ gps: "running", zone: "running", upload: "running" });
    const session = sessionRef.current ?? (sessionRef.current = startZoneSession());

    // FAIL CLOSED (field order 2026-07-27): Nearby-devices permission is REQUIRED
    // for attendance — a silent skip here is how ghost "no beacon" punches happened.
    const perm = await session.permissionReady;
    if (perm === "denied" || perm === "blocked") {
      showToast(t("att.blePermRequired"), "error");
      setSteps(null);
      router.replace("/(tabs)/home");
      return;
    }

    // Everything below runs in PARALLEL (strictly sequential in ≤1.0.16):
    // compress→upload | GPS fix | zone wait (≤5s cap) | reverse-geocode (≤3s, display-only)
    const compressP = (async () => {
      const t = Date.now();
      let out = uri;
      try {
        const c = await ImageManipulator.manipulateAsync(uri, [{ resize: { width: 720 } }], {
          compress: 0.7,
          format: ImageManipulator.SaveFormat.JPEG,
        });
        out = c.uri;
      } catch {
        // upload original if compression fails
      }
      T.compressMs = Date.now() - t;
      return out;
    })();
    const uploadP = compressP.then(async (su) => {
      const t = Date.now();
      const up = await uploadFile(su, "selfie.jpg");
      T.uploadMs = Date.now() - t;
      return up;
    });
    uploadP.catch(() => undefined); // handled at the await below
    const gpsP = (async () => {
      const t = Date.now();
      const r = await acquireGps(8000);
      T.gpsMs = Date.now() - t;
      return r;
    })();
    const zoneP = (async () => {
      const t = Date.now();
      // NEVER hold the punch hostage: pre-warmed sessions usually already have the
      // hit here (0ms); otherwise wait at most 5s and attach late if it arrives.
      const h = await session.waitForHit(5000);
      T.zoneWaitMs = Date.now() - t;
      return h;
    })();

    const [{ fix }, ble] = await Promise.all([gpsP, zoneP]);
    setStep("gps", fix ? "ok" : "skip");
    setStep("zone", ble ? "ok" : "skip");
    const addressP: Promise<string | null> = fix
      ? Promise.race([
          reverseGeocode(fix.lat, fix.lng),
          new Promise<null>((resolve) => setTimeout(() => resolve(null), 3000)),
        ])
      : Promise.resolve(null);

    const payload: Record<string, unknown> = {
      gps_lat: fix?.lat ?? null,
      gps_lng: fix?.lng ?? null,
      ...beaconPayload(ble),
    };
    const selfieUri = await compressP;

    try {
      const uploaded = await uploadP;
      const tSubmit = Date.now();
      const record = (await punchIn({ ...payload, selfie_key: uploaded.key })) as AttendanceRecord;
      T.submitMs = Date.now() - tSubmit;
      setStep("upload", "ok");
      T.totalMs = Date.now() - t0;
      T.sessionPermissionMs = session.timings.permissionMs ?? -1;
      T.sessionRegistryMs = session.timings.registryMs ?? -1;
      T.sessionFirstMatchMs = session.timings.firstMatchMs ?? -1;
      T.at = new Date().toISOString();
      void storage.setItem("hogo.lastPunchTimings", JSON.stringify(T));
      if (ble) {
        session.stop();
      } else {
        // LATE ATTACH: the background scan keeps running (≤60s). If it matches after
        // submit, upgrade the stored row — the worker never waited for it.
        session.onceMatched((hit) => {
          void attachBeacon(record.id, beaconPayload(hit) as Record<string, unknown>).catch(
            () => undefined,
          );
        });
      }
      const address = await addressP;
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
      session.stop();
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
