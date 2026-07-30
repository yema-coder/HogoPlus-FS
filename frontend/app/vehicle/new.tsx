import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { Camera, LogIn, LogOut } from "lucide-react-native";
import React, { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "@/src/api/client";
import { aiAnpr, createVehicleLog } from "@/src/api/endpoints";
import { startZoneSession, type ZoneSession } from "@/src/ble/zoneSession";
import { BigButton } from "@/src/components/BigButton";
import { PhotoCaptureModal } from "@/src/components/PhotoCaptureModal";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { VoiceFieldInput } from "@/src/forms/fields/VoiceFieldInput";
import { useOutboxStore } from "@/src/offline/outbox";
import { colors, fonts, radius, shadow, sizes, spacing, type } from "@/src/theme/tokens";

const TYPES = [
  { key: "truck", emoji: "🚛" },
  { key: "tractor", emoji: "🚜" },
  { key: "tempo", emoji: "🛻" },
  { key: "car", emoji: "🚗" },
  { key: "bike", emoji: "🏍️" },
  { key: "bus", emoji: "🚌" },
  { key: "jcb", emoji: "🚧" },
  { key: "bullock_cart", emoji: "🐂" },
  { key: "other", emoji: "🚙" },
] as const;

const PURPOSES = ["cane", "delivery", "dispatch", "visitor", "contractor", "official", "other"] as const;

export default function VehicleNewScreen() {
  const { t } = useTranslation();
  const router = useRouter();
  const enqueue = useOutboxStore((s) => s.enqueue);

  const [direction, setDirection] = useState<"in" | "out">("in");
  const [plate, setPlate] = useState("");
  const [vehicleType, setVehicleType] = useState<string>("truck");
  const [purpose, setPurpose] = useState<string | null>(null);
  const [driverName, setDriverName] = useState("");
  const [voiceUri, setVoiceUri] = useState<string | undefined>(undefined);
  const [photoKey, setPhotoKey] = useState<string | null>(null);
  const [anprUsed, setAnprUsed] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [zone, setZone] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // gate zone auto-tag: pre-warm the BLE scan the moment the screen opens
  const sessionRef = useRef<ZoneSession | null>(null);
  useEffect(() => {
    const session = startZoneSession();
    sessionRef.current = session;
    void session.waitForHit(6000).then((hit) => {
      if (hit?.zone) setZone(hit.zone);
    });
    return () => session.stop();
  }, []);

  const onPlatePhoto = async (uri: string) => {
    setCameraOpen(false);
    setScanning(true);
    try {
      const up = await uploadFile(uri, "plate.jpg");
      setPhotoKey(up.key);
      const res = await aiAnpr(up.key);
      if (res.plate) {
        setPlate(res.plate);
        setAnprUsed(true);
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      } else {
        showToast(t("veh.anprMiss"), "error");
      }
    } catch {
      // photo kept if uploaded; manual entry always available
      showToast(t("veh.anprMiss"), "error");
    } finally {
      setScanning(false);
    }
  };

  const submit = async () => {
    const cleaned = plate.replace(/[\s-]/g, "").toUpperCase();
    if (cleaned.length < 3) {
      showToast(t("veh.plateNeeded"), "error");
      return;
    }
    setSubmitting(true);
    const clientUuid = `veh-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    const payload: Record<string, unknown> = {
      plate: cleaned,
      vehicle_type: vehicleType,
      direction,
      driver_name: driverName.trim() || null,
      purpose: purpose ? t(`veh.purpose.${purpose}`, { lng: "en" }) : null,
      photo_key: photoKey,
      gate_zone: zone,
      anpr_used: anprUsed,
      client_uuid: clientUuid,
    };
    try {
      if (voiceUri) {
        const up = await uploadFile(voiceUri, "voice_note.m4a").catch(() => null);
        if (up) payload.voice_note_key = up.key;
      }
      await createVehicleLog(payload);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      showToast(t("veh.saved"), "success");
      router.back();
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        // offline — queue with the same client_uuid (idempotent replay server-side)
        await enqueue({
          type: "vehicle",
          payload: { ...payload, logged_at: new Date().toISOString() },
          photoUri: null,
          photoName: "",
          photoField: "",
          files: voiceUri
            ? [{ field: "voice_note_key", uri: voiceUri, name: "voice_note.m4a", kind: "audio" }]
            : undefined,
        });
        showToast(t("veh.queued"), "success");
        router.back();
      } else {
        showToast(t("errors.server"), "error");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} testID="vehicle-new-screen">
      <ScreenHeader title={t("veh.newTitle")} />
      <KeyboardAwareScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        bottomOffset={24}
      >
        {/* IN / OUT — giant glove-friendly toggle */}
        <View style={styles.dirRow}>
          <Pressable
            testID="vehicle-dir-in"
            onPress={() => setDirection("in")}
            style={[styles.dirBtn, direction === "in" && styles.dirBtnIn]}
          >
            <LogIn size={26} color={direction === "in" ? "#FFFFFF" : colors.success} strokeWidth={2.6} />
            <Text style={[styles.dirBtnText, direction === "in" && styles.dirBtnTextActive]}>
              {t("veh.in")}
            </Text>
          </Pressable>
          <Pressable
            testID="vehicle-dir-out"
            onPress={() => setDirection("out")}
            style={[styles.dirBtn, direction === "out" && styles.dirBtnOut]}
          >
            <LogOut size={26} color={direction === "out" ? "#FFFFFF" : colors.accent} strokeWidth={2.6} />
            <Text style={[styles.dirBtnText, direction === "out" && styles.dirBtnTextActive]}>
              {t("veh.out")}
            </Text>
          </Pressable>
        </View>

        {/* Plate: ANPR photo AND manual typing — both always available */}
        <Text style={styles.sectionTitle}>{t("veh.plateTitle")}</Text>
        <Pressable
          testID="vehicle-scan-plate"
          onPress={() => setCameraOpen(true)}
          disabled={scanning}
          style={({ pressed }) => [styles.scanBtn, shadow.card, { opacity: pressed ? 0.9 : 1 }]}
        >
          {scanning ? (
            <ActivityIndicator color={colors.primary} />
          ) : (
            <Camera size={28} color={colors.primary} strokeWidth={2.2} />
          )}
          <Text style={styles.scanText}>{scanning ? t("veh.scanning") : t("veh.scanPlate")}</Text>
        </Pressable>
        <TextInput
          testID="vehicle-plate-input"
          style={styles.plateInput}
          value={plate}
          onChangeText={(v) => {
            setPlate(v.toUpperCase());
            setAnprUsed(false);
          }}
          placeholder="MH 12 AB 1234"
          placeholderTextColor={colors.muted}
          autoCapitalize="characters"
          autoCorrect={false}
          maxLength={15}
        />
        {anprUsed ? <Text style={styles.anprChip}>✓ {t("veh.anprOk")}</Text> : null}

        {/* Vehicle type — icon pick-list */}
        <Text style={styles.sectionTitle}>{t("veh.typeTitle")}</Text>
        <View style={styles.typeGrid}>
          {TYPES.map((tp) => (
            <Pressable
              key={tp.key}
              testID={`vehicle-type-${tp.key}`}
              onPress={() => setVehicleType(tp.key)}
              style={[styles.typeTile, vehicleType === tp.key && styles.typeTileActive]}
            >
              <Text style={styles.typeEmoji}>{tp.emoji}</Text>
              <Text
                style={[styles.typeLabel, vehicleType === tp.key && styles.typeLabelActive]}
                numberOfLines={1}
              >
                {t(`veh.type.${tp.key}`)}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Purpose — chips, no typing needed */}
        <Text style={styles.sectionTitle}>{t("veh.purposeTitle")}</Text>
        <View style={styles.chipRow}>
          {PURPOSES.map((p) => (
            <Pressable
              key={p}
              testID={`vehicle-purpose-${p}`}
              onPress={() => setPurpose(purpose === p ? null : p)}
              style={[styles.chip, purpose === p && styles.chipActive]}
            >
              <Text style={[styles.chipText, purpose === p && styles.chipTextActive]}>
                {t(`veh.purpose.${p}`)}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Driver (optional typing) + voice note fallback */}
        <Text style={styles.sectionTitle}>{t("veh.driverTitle")}</Text>
        <TextInput
          testID="vehicle-driver-input"
          style={styles.input}
          value={driverName}
          onChangeText={setDriverName}
          placeholder={t("veh.driverPh")}
          placeholderTextColor={colors.muted}
        />
        <VoiceFieldInput value={voiceUri} onChange={setVoiceUri} testID="vehicle-voice" />

        {/* Gate zone auto-tag */}
        <View style={styles.zoneRow} testID="vehicle-zone-chip">
          <Text style={styles.zoneText}>
            📍 {zone ?? t("veh.zoneSearching")}
          </Text>
        </View>

        <BigButton
          testID="vehicle-submit"
          label={direction === "in" ? t("veh.submitIn") : t("veh.submitOut")}
          icon={direction === "in" ? LogIn : LogOut}
          variant={direction === "in" ? "success" : "primary"}
          height={64}
          loading={submitting}
          onPress={() => void submit()}
        />
      </KeyboardAwareScrollView>

      <PhotoCaptureModal
        visible={cameraOpen}
        label={t("veh.scanPlate")}
        onClose={() => setCameraOpen(false)}
        onCaptured={(uri) => void onPlatePhoto(uri)}
        testIDPrefix="plate-cam"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.xxl },
  dirRow: { flexDirection: "row", gap: spacing.md },
  dirBtn: {
    flex: 1,
    minHeight: 64,
    borderRadius: radius.lg,
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: colors.border,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
  },
  dirBtnIn: { backgroundColor: colors.success, borderColor: colors.success },
  dirBtnOut: { backgroundColor: colors.accent, borderColor: colors.accent },
  dirBtnText: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  dirBtnTextActive: { color: "#FFFFFF" },
  sectionTitle: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.muted,
    marginTop: spacing.sm,
  },
  scanBtn: {
    minHeight: 60,
    borderRadius: radius.lg,
    backgroundColor: "#FFFFFF",
    borderWidth: 2,
    borderColor: colors.primary,
    borderStyle: "dashed",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
  },
  scanText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.primary },
  plateInput: {
    minHeight: 58,
    borderRadius: radius.lg,
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.bold,
    fontSize: 22,
    letterSpacing: 2,
    color: colors.text,
    textAlign: "center",
  },
  anprChip: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.success, textAlign: "center" },
  typeGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  typeTile: {
    width: "31%",
    flexGrow: 1,
    minHeight: 72,
    borderRadius: radius.md,
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
  },
  typeTileActive: { borderWidth: 2, borderColor: colors.primary, backgroundColor: "#E8F1F3" },
  typeEmoji: { fontSize: 26 },
  typeLabel: { fontFamily: fonts.semiBold, fontSize: type.xs, color: colors.muted },
  typeLabelActive: { color: colors.primary },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    minHeight: 44,
    borderRadius: 22,
    paddingHorizontal: spacing.md,
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  chipTextActive: { color: "#FFFFFF" },
  input: {
    minHeight: 52,
    borderRadius: radius.lg,
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
  },
  zoneRow: {
    backgroundColor: "#E8F1F3",
    borderRadius: radius.md,
    padding: spacing.md,
    alignItems: "center",
  },
  zoneText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.primary },
});
