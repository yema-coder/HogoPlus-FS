import { Camera } from "expo-camera";
import * as Location from "expo-location";
import {
  Bluetooth,
  Camera as CameraIcon,
  Check,
  MapPin,
  Navigation,
  Settings,
  X,
} from "lucide-react-native";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Linking, Platform, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { getBleScanner, getBleState, checkBlePermissions, requestBlePermissions } from "@/src/ble/BleScanner";
import { BigButton } from "@/src/components/BigButton";
import { EyeLoader } from "@/src/components/EyeLoader";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

type PermState = "ok" | "ask" | "blocked";
type RadioState = "ok" | "off";

interface GuardResult {
  camera: PermState | "na";
  location: PermState | "na";
  gps: RadioState | "na";
  bluetooth: RadioState | "na";
  blePerm: PermState | "na";
}

interface Props {
  /** which checks to run — omit those the wrapped screen already handles */
  camera?: boolean;
  location?: boolean;
  gps?: boolean;
  bluetooth?: boolean;
  /** strict: GPS/Bluetooth/BLE-permission failures BLOCK (no Continue-anyway) */
  strict?: boolean;
  children: React.ReactNode;
}

/**
 * Prompt 17 Part D: permission & radio guards BEFORE capture. Runs the checks
 * once on mount (requesting undetermined permissions — the user just expressed
 * clear capture intent); if everything passes, children render immediately.
 * Otherwise a checklist explains what's off with per-row fixes. Camera is the
 * only HARD requirement — GPS/Bluetooth failures allow "Continue anyway"
 * because punch/incident flows degrade gracefully (flagged / no zone).
 * Once passed, the guard latches: children are never unmounted afterwards.
 */
export function CaptureGuards({ camera, location, gps, bluetooth, strict, children }: Props) {
  const { t } = useTranslation();
  const [result, setResult] = useState<GuardResult | null>(null);
  const [ready, setReady] = useState(Platform.OS === "web");
  const requestedOnce = useRef(false);

  const run = useCallback(
    async (requestMissing: boolean) => {
      const next: GuardResult = { camera: "na", location: "na", gps: "na", bluetooth: "na", blePerm: "na" };
      try {
        if (camera) {
          let p = await Camera.getCameraPermissionsAsync();
          if (p.status === "undetermined" && requestMissing) p = await Camera.requestCameraPermissionsAsync();
          next.camera = p.granted ? "ok" : p.canAskAgain ? "ask" : "blocked";
        }
        if (location || gps) {
          let p = await Location.getForegroundPermissionsAsync();
          if (p.status === "undetermined" && requestMissing) p = await Location.requestForegroundPermissionsAsync();
          if (location) next.location = p.granted ? "ok" : p.canAskAgain ? "ask" : "blocked";
          if (gps) {
            const on = await Location.hasServicesEnabledAsync().catch(() => true);
            next.gps = on ? "ok" : "off";
          }
        }
        if (bluetooth) {
          // Nearby-devices RUNTIME permission (Android 12+) — field failure 2026-07-27:
          // checking only the adapter state let scans fail silently after a denial.
          let perm = await checkBlePermissions();
          if (perm === "denied" && requestMissing) perm = await requestBlePermissions();
          next.blePerm =
            perm === "granted" ? "ok" : perm === "unavailable" ? "na" : perm === "blocked" ? "blocked" : "ask";
          const state = await getBleState();
          if (state === "on") next.bluetooth = "ok";
          else if (state === "off") next.bluetooth = "off";
          // 'unknown': Expo Go / web have no radio access → pass. On a REAL build in
          // strict mode an unreadable radio state must BLOCK (fail closed).
          else next.bluetooth = strict && getBleScanner().isReal ? "off" : "na";
        }
      } catch {
        // any check failure → fail open (never block capture on guard errors)
      }
      setResult(next);
      const pass =
        (next.camera === "ok" || next.camera === "na") &&
        (next.location === "ok" || next.location === "na") &&
        (next.gps === "ok" || next.gps === "na") &&
        (next.bluetooth === "ok" || next.bluetooth === "na") &&
        (next.blePerm === "ok" || next.blePerm === "na");
      if (pass) setReady(true);
      return next;
    },
    [camera, location, gps, bluetooth, strict],
  );

  useEffect(() => {
    if (ready || requestedOnce.current) return;
    requestedOnce.current = true;
    void run(true);
  }, [ready, run]);

  // returning from Settings / GPS toggle → recheck automatically
  useEffect(() => {
    if (ready) return;
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active") void run(false);
    });
    return () => sub.remove();
  }, [ready, run]);

  // strict mode: quick-settings toggles don't background the app — poll lightly
  // so switching GPS/Bluetooth ON unblocks without any tap.
  useEffect(() => {
    if (ready || !strict) return;
    const timer = setInterval(() => void run(false), 3000);
    return () => clearInterval(timer);
  }, [ready, strict, run]);

  if (ready) return <>{children}</>;

  if (!result) {
    return (
      <View style={styles.center} testID="capture-guards-checking">
        <EyeLoader size={32} />
      </View>
    );
  }

  const hardFail =
    result.camera === "ask" ||
    result.camera === "blocked" ||
    (strict === true &&
      (result.location === "ask" ||
        result.location === "blocked" ||
        result.gps === "off" ||
        result.bluetooth === "off" ||
        result.blePerm === "ask" ||
        result.blePerm === "blocked"));

  const stateIcon = (ok: boolean) =>
    ok ? (
      <Check size={22} color={colors.success} strokeWidth={3} />
    ) : (
      <X size={22} color={colors.danger} strokeWidth={3} />
    );

  const rows: {
    key: string;
    icon: React.ReactNode;
    label: string;
    ok: boolean;
    hint?: string;
    action?: { label: string; onPress: () => void };
  }[] = [];

  if (result.camera !== "na") {
    rows.push({
      key: "camera",
      icon: <CameraIcon size={24} color={colors.primary} strokeWidth={2} />,
      label: t("guard.camera"),
      ok: result.camera === "ok",
      action:
        result.camera === "ask"
          ? { label: t("guard.allow"), onPress: () => void run(true) }
          : result.camera === "blocked"
            ? { label: t("common.openSettings"), onPress: () => void Linking.openSettings() }
            : undefined,
    });
  }
  if (result.location !== "na") {
    rows.push({
      key: "location",
      icon: <MapPin size={24} color={colors.primary} strokeWidth={2} />,
      label: t("guard.location"),
      ok: result.location === "ok",
      action:
        result.location === "ask"
          ? { label: t("guard.allow"), onPress: () => void run(true) }
          : result.location === "blocked"
            ? { label: t("common.openSettings"), onPress: () => void Linking.openSettings() }
            : undefined,
    });
  }
  if (result.gps !== "na") {
    rows.push({
      key: "gps",
      icon: <Navigation size={24} color={colors.primary} strokeWidth={2} />,
      label: t("guard.gps"),
      ok: result.gps === "ok",
      hint: result.gps === "off" ? t("guard.gpsHint") : undefined,
      action:
        result.gps === "off"
          ? {
              label: t("guard.enableGps"),
              onPress: () => {
                if (Platform.OS === "android") {
                  void Location.enableNetworkProviderAsync()
                    .then(() => void run(false))
                    .catch(() => undefined);
                } else {
                  void Linking.openSettings();
                }
              },
            }
          : undefined,
    });
  }
  if (result.blePerm !== "na") {
    rows.push({
      key: "blePerm",
      icon: <Bluetooth size={24} color={colors.primary} strokeWidth={2} />,
      label: t("guard.blePerm"),
      ok: result.blePerm === "ok",
      hint: result.blePerm !== "ok" ? t("guard.blePermHint") : undefined,
      action:
        result.blePerm === "ask"
          ? { label: t("guard.allow"), onPress: () => void run(true) }
          : result.blePerm === "blocked"
            ? { label: t("common.openSettings"), onPress: () => void Linking.openSettings() }
            : undefined,
    });
  }
  if (result.bluetooth !== "na") {
    rows.push({
      key: "bluetooth",
      icon: <Bluetooth size={24} color={colors.primary} strokeWidth={2} />,
      label: t("guard.bluetooth"),
      ok: result.bluetooth === "ok",
      hint: result.bluetooth === "off" ? t("guard.bleHint") : undefined,
    });
  }

  return (
    <View style={styles.wrap} testID="capture-guards-checklist">
      <Text style={styles.title}>{t("guard.title")}</Text>
      <Text style={styles.body}>{strict ? t("guard.strictBody") : t("guard.body")}</Text>
      <View style={styles.rows}>
        {rows.map((row) => (
          <View key={row.key} style={styles.row} testID={`guard-row-${row.key}`}>
            <View style={styles.rowIcon}>{row.icon}</View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowLabel}>{row.label}</Text>
              {row.hint ? <Text style={styles.rowHint}>{row.hint}</Text> : null}
              {row.action ? (
                <Text
                  style={styles.rowAction}
                  onPress={row.action.onPress}
                  accessibilityRole="button"
                  testID={`guard-action-${row.key}`}
                >
                  {row.key === "camera" || row.key === "location" ? (
                    <Settings size={13} color={colors.accent} strokeWidth={2.4} />
                  ) : null}{" "}
                  {row.action.label}
                </Text>
              ) : null}
            </View>
            <View style={styles.rowState}>{stateIcon(row.ok)}</View>
          </View>
        ))}
      </View>
      <View style={styles.actions}>
        {!hardFail ? (
          <BigButton
            testID="guard-continue-button"
            label={t("guard.continue")}
            onPress={() => setReady(true)}
          />
        ) : null}
        <BigButton
          testID="guard-recheck-button"
          label={t("guard.recheck")}
          variant="outline"
          onPress={() => void run(true)}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.background,
  },
  wrap: {
    flex: 1,
    backgroundColor: colors.background,
    padding: sizes.screenPadding,
    justifyContent: "center",
  },
  title: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
    textAlign: "center",
  },
  body: {
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.xs,
    marginBottom: spacing.xl,
  },
  rows: { gap: spacing.md },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  rowIcon: { width: 32, alignItems: "center" },
  rowLabel: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  rowHint: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, marginTop: 2 },
  rowAction: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.accent,
    marginTop: spacing.xs,
  },
  rowState: { width: 28, alignItems: "center" },
  actions: { marginTop: spacing.xxl, gap: spacing.md },
});
