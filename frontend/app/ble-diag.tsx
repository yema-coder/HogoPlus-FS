/**
 * v1.0.16 TEMPORARY BLE DIAGNOSTIC SCREEN (field instrumentation).
 * Hidden entry: long-press the avatar on the Profile tab.
 * Shows, live: permission/radio state, the fetched beacon registry, every BLE device
 * a 15s scan sees with parsed iBeacon candidates and WHY each was accepted/rejected.
 * "Send to server" posts the full report to POST /api/attendance/ble-diag so the
 * output can be shared verbatim. English-only by design (owner/debug tool).
 */
import Constants from "expo-constants";
import * as Location from "expo-location";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  PermissionsAndroid,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { beaconRegistry, sendBleDiag } from "@/src/api/endpoints";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import {
  getBleScanner,
  getBleState,
  requestBlePermissions,
  type BleDiagScan,
} from "@/src/ble/BleScanner";
import { colors, fonts, spacing } from "@/src/theme/tokens";
import { storage } from "@/src/utils/storage";

type Registry = Awaited<ReturnType<typeof beaconRegistry>>;

interface PermState {
  scan: boolean | null;
  connect: boolean | null;
  fineLocation: boolean | null;
  coarseLocation: boolean | null;
  btRadio: string;
  locationServices: boolean | null;
}

const VERDICT_COLOR: Record<string, string> = {
  matched: colors.success,
  mac_matched: colors.success,
  minor_not_registered: colors.warning,
  major_mismatch: colors.warning,
  uuid_mismatch: colors.warning,
  no_ibeacon_frame: colors.muted,
  no_mfg_data: colors.muted,
};

export default function BleDiagScreen() {
  const [perm, setPerm] = useState<PermState | null>(null);
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [regError, setRegError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<BleDiagScan | null>(null);
  const [sending, setSending] = useState(false);
  const [punchTimings, setPunchTimings] = useState<Record<string, number | string> | null>(null);

  const refreshPerms = useCallback(async () => {
    const isAndroid31 = Platform.OS === "android" && Number(Platform.Version) >= 31;
    const check = async (p: string) => {
      try {
        return await PermissionsAndroid.check(p as never);
      } catch {
        return null;
      }
    };
    let locationServices: boolean | null = null;
    try {
      locationServices = await Location.hasServicesEnabledAsync();
    } catch {
      locationServices = null;
    }
    setPerm({
      scan: isAndroid31 ? await check(PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN) : null,
      connect: isAndroid31 ? await check(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT) : null,
      fineLocation:
        Platform.OS === "android"
          ? await check(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION)
          : null,
      coarseLocation:
        Platform.OS === "android"
          ? await check(PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION)
          : null,
      btRadio: await getBleState(),
      locationServices,
    });
  }, []);

  const loadRegistry = useCallback(async () => {
    try {
      const reg = await beaconRegistry();
      setRegistry(reg);
      setRegError(null);
    } catch (e) {
      setRegError(String(e));
    }
  }, []);

  useEffect(() => {
    void refreshPerms();
    void loadRegistry();
    void storage
      .getItem<string>("hogo.lastPunchTimings", "")
      .then((raw) => {
        if (raw) setPunchTimings(JSON.parse(String(raw)) as Record<string, number | string>);
      })
      .catch(() => undefined);
  }, [refreshPerms, loadRegistry]);

  const runScan = async () => {
    if (!registry) return;
    setScanning(true);
    setResult(null);
    const status = await requestBlePermissions();
    await refreshPerms();
    if (status !== "granted" && status !== "unavailable") {
      setResult({
        supported: false, scanMs: 0, callbacks: 0, devicesSeen: 0, matchedCount: 0,
        error: `Nearby-devices permission: ${status}`, devices: [],
      });
      setScanning(false);
      return;
    }
    const scan = await getBleScanner().scanDiagnostics(15000, registry);
    setResult(scan);
    setScanning(false);
  };

  const send = async () => {
    if (!result) return;
    setSending(true);
    try {
      const report = {
        app_version: Constants.expoConfig?.version ?? "?",
        platform: `${Platform.OS} ${Platform.Version}`,
        at: new Date().toISOString(),
        permissions: perm,
        registry: registry
          ? {
              ibeacons: registry.ibeacons.length,
              macs: registry.macs.length,
              entries: registry.ibeacons.map((i) => `${i.uuid}:${i.major}:${i.minor}=${i.zone_en ?? ""}`),
            }
          : { error: regError },
        scan: result,
        last_punch_timings: punchTimings,
      };
      await sendBleDiag(report);
      showToast("Report sent to server ✓", "success");
    } catch (e) {
      showToast(`Send failed: ${String(e)}`, "error");
    }
    setSending(false);
  };

  const yn = (v: boolean | null) => (v === null ? "n/a" : v ? "YES" : "NO");
  const permColor = (v: boolean | null) => (v === null ? colors.muted : v ? colors.success : colors.danger);

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="ble-diag-screen">
      <ScreenHeader title="BLE Diagnostics" />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Permissions & radio</Text>
          {perm ? (
            <>
              <Row label="BLUETOOTH_SCAN (Nearby devices)" value={yn(perm.scan)} color={permColor(perm.scan)} />
              <Row label="BLUETOOTH_CONNECT" value={yn(perm.connect)} color={permColor(perm.connect)} />
              <Row label="ACCESS_FINE_LOCATION (precise)" value={yn(perm.fineLocation)} color={permColor(perm.fineLocation)} />
              <Row label="ACCESS_COARSE_LOCATION" value={yn(perm.coarseLocation)} color={permColor(perm.coarseLocation)} />
              <Row label="Bluetooth radio" value={perm.btRadio} color={perm.btRadio === "on" ? colors.success : colors.danger} />
              <Row label="Location services" value={yn(perm.locationServices)} color={permColor(perm.locationServices)} />
            </>
          ) : (
            <ActivityIndicator color={colors.primary} />
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>
            Registry {registry ? `(${registry.ibeacons.length} iBeacons, ${registry.macs.length} MACs)` : ""}
          </Text>
          {regError ? <Text style={styles.err}>{regError}</Text> : null}
          {registry?.ibeacons.map((i) => (
            <Text key={`${i.uuid}:${i.major}:${i.minor}`} style={styles.mono}>
              {i.uuid.slice(0, 8)}… {i.major}/{i.minor} → {i.zone_en ?? "?"}
            </Text>
          ))}
        </View>

        {punchTimings ? (
          <View style={styles.card} testID="punch-timings">
            <Text style={styles.cardTitle}>Last punch timing breakdown (ms)</Text>
            {Object.entries(punchTimings).map(([k, v]) => (
              <Row key={k} label={k} value={String(v)} color={colors.text} />
            ))}
          </View>
        ) : null}

        <TouchableOpacity
          style={[styles.btn, scanning && styles.btnDisabled]}
          onPress={() => void runScan()}
          disabled={scanning || !registry}
          testID="ble-diag-scan"
        >
          <Text style={styles.btnText}>{scanning ? "Scanning 15s…" : "▶ Run 15s scan"}</Text>
        </TouchableOpacity>

        {result ? (
          <View style={styles.card} testID="ble-diag-result">
            <Text style={styles.cardTitle}>
              Scan: {result.devicesSeen} devices · {result.callbacks} callbacks · {result.matchedCount} MATCHED
            </Text>
            {result.error ? <Text style={styles.err}>{result.error}</Text> : null}
            {result.devices.map((d) => (
              <View key={d.id} style={styles.device}>
                <Text style={[styles.deviceHead, { color: VERDICT_COLOR[d.verdict] ?? colors.text }]}>
                  {d.verdict.toUpperCase()} · {d.id} · {d.rssi ?? "?"}dBm · {d.frames}fr
                  {d.name ? ` · ${d.name}` : ""}
                </Text>
                {d.ibeacons.map((i) => (
                  <Text key={`${i.uuid}:${i.major}:${i.minor}`} style={styles.mono}>
                    ↳ {i.uuid} {i.major}/{i.minor} → {i.verdict}
                  </Text>
                ))}
                {d.ibeacons.length === 0 && (d.mfg.length > 0 || d.raw.length > 0) ? (
                  <Text style={styles.mono} numberOfLines={2}>
                    ↳ mfg: {d.mfg.join(" | ") || "—"}
                  </Text>
                ) : null}
              </View>
            ))}
            <TouchableOpacity
              style={[styles.btn, styles.btnSend, sending && styles.btnDisabled]}
              onPress={() => void send()}
              disabled={sending}
              testID="ble-diag-send"
            >
              <Text style={styles.btnText}>{sending ? "Sending…" : "⇪ Send report to server"}</Text>
            </TouchableOpacity>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, { color }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: spacing.md, paddingBottom: 48, gap: spacing.md },
  card: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    padding: spacing.md,
    gap: 6,
  },
  cardTitle: { fontFamily: fonts.bold, fontSize: 15, color: colors.text, marginBottom: 4 },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", minHeight: 24 },
  rowLabel: { fontFamily: fonts.regular, fontSize: 13, color: colors.muted, flex: 1 },
  rowValue: { fontFamily: fonts.bold, fontSize: 13 },
  mono: {
    fontFamily: Platform.select({ ios: "Courier", default: "monospace" }),
    fontSize: 11,
    color: colors.text,
  },
  err: { fontFamily: fonts.regular, fontSize: 12, color: colors.danger },
  btn: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
    minHeight: 48,
    justifyContent: "center",
  },
  btnSend: { backgroundColor: colors.accent, marginTop: spacing.sm },
  btnDisabled: { opacity: 0.5 },
  btnText: { fontFamily: fonts.bold, fontSize: 15, color: "#FFFFFF" },
  device: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingVertical: 6,
    gap: 2,
  },
  deviceHead: { fontFamily: fonts.bold, fontSize: 12 },
});
