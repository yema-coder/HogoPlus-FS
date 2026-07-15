import dayjs from "dayjs";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  Camera as CameraIcon,
  ChevronDown,
  MapPin,
  MapPinOff,
  RefreshCcw,
  Settings,
} from "lucide-react-native";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "@/src/api/client";
import { createIncident, listDepartments } from "@/src/api/endpoints";
import type { DepartmentItem, Incident } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { categoryDef } from "@/src/constants/categories";
import { departmentIcon } from "@/src/constants/departments";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { burnInSafe } from "@/src/utils/burnIn";
import { acquireGps, type GpsFix } from "@/src/utils/gps";

interface Shot {
  uri: string;
  width: number;
  height: number;
}

type GpsStatus = "searching" | "ok" | "none" | "blocked";

/** Taps 2 & 3 of the incident flow: shutter, watermark burn-in, submit. */
export default function IncidentCapture() {
  const router = useRouter();
  const { t } = useTranslation();
  const { category } = useLocalSearchParams<{ category: string }>();
  const def = categoryDef(category ?? "other");
  const CatIcon = def.icon;
  const profile = useAuthStore((s) => s.profile);
  const enqueue = useOutboxStore((s) => s.enqueue);
  const { width: windowW } = useWindowDimensions();

  const [permission, requestPermission] = useCameraPermissions();
  const [shot, setShot] = useState<Shot | null>(null);
  const [capturedAt, setCapturedAt] = useState<number>(0);
  const [capturing, setCapturing] = useState(false);
  const [gps, setGps] = useState<GpsFix | null>(null);
  const [gpsStatus, setGpsStatus] = useState<GpsStatus>("searching");
  const [dept, setDept] = useState(profile?.department_code ?? "PRODUCTION");
  const [desc, setDesc] = useState("");
  const [deptModal, setDeptModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const cameraRef = useRef<CameraView>(null);
  const watermarkRef = useRef<View>(null);

  const departments = useCachedFetch<DepartmentItem[]>("departments", listDepartments);
  const selectedDept = departments.data?.find((d) => d.code === dept) ?? null;

  useEffect(() => {
    let active = true;
    void (async () => {
      const res = await acquireGps(10000);
      if (!active) return;
      setGps(res.fix);
      setGpsStatus(res.fix ? "ok" : res.blocked ? "blocked" : "none");
    })();
    return () => {
      active = false;
    };
  }, []);

  const capture = async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.85 });
      if (photo?.uri) {
        setShot({ uri: photo.uri, width: photo.width || 1200, height: photo.height || 1600 });
        setCapturedAt(Date.now());
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => undefined);
      }
    } catch {
      showToast(t("errors.generic"), "error");
    } finally {
      setCapturing(false);
    }
  };

  /** Burn watermark into pixels via view-shot, then compress. Never throws for a valid shot. */
  const buildFinalImage = async (): Promise<string> => {
    if (!shot) throw new Error("no shot");
    return burnInSafe(watermarkRef, shot.uri, shot.width, shot.height);
  };

  const submit = async () => {
    if (!shot || submitting) return;
    setSubmitting(true);
    const payload: Record<string, unknown> = {
      category: def.code,
      department_code: dept,
      gps_lat: gps?.lat ?? null,
      gps_lng: gps?.lng ?? null,
      description: desc.trim() || null,
      severity: "normal",
    };
    let finalUri: string;
    try {
      finalUri = await buildFinalImage();
    } catch (err) {
      console.warn("buildFinalImage failed:", err);
      showToast(t("errors.generic"), "error");
      setSubmitting(false);
      return;
    }
    try {
      const uploaded = await uploadFile(finalUri, "incident.jpg");
      const incident = await createIncident({ ...payload, photo_key: uploaded.key }) as Incident;
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      router.replace({ pathname: "/incident/success", params: { queued: "0", rid: incident.id } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        await enqueue({
          type: "incident",
          payload,
          photoUri: finalUri,
          photoName: "incident.jpg",
          photoField: "photo_key",
        });
        router.replace({ pathname: "/incident/success", params: { queued: "1" } });
      } else if (e instanceof ApiError && e.status === 401) {
        showToast(t("errors.sessionExpired"), "error");
      } else if (e instanceof ApiError && (e.status === 400 || e.status === 413)) {
        const extra = typeof e.detail === "string" ? ` (${e.detail})` : "";
        showToast(`${t("errors.uploadRejected")}${extra}`, "error");
        setSubmitting(false);
      } else {
        showToast(t("errors.server"), "error");
        setSubmitting(false);
      }
    }
  };

  const gpsChip = () => {
    if (gpsStatus === "searching") {
      return (
        <View style={styles.gpsChip} testID="gps-chip-searching">
          <ActivityIndicator size="small" color="#FFFFFF" />
          <Text style={styles.gpsChipText}>{t("incident.gpsSearching")}</Text>
        </View>
      );
    }
    if (gpsStatus === "ok") {
      return (
        <View style={[styles.gpsChip, { backgroundColor: colors.success }]} testID="gps-chip-ok">
          <MapPin size={16} color="#FFFFFF" strokeWidth={2.4} />
          <Text style={styles.gpsChipText}>{t("incident.gpsOk")}</Text>
        </View>
      );
    }
    return (
      <Pressable
        testID="gps-chip-none"
        onPress={() => {
          if (gpsStatus === "blocked") void Linking.openSettings();
        }}
        style={[styles.gpsChip, { backgroundColor: colors.warning }]}
      >
        <MapPinOff size={16} color={colors.onWarning} strokeWidth={2.4} />
        <Text style={[styles.gpsChipText, { color: colors.onWarning }]}>
          {gpsStatus === "blocked" ? t("common.openSettings") : t("incident.gpsNone")}
        </Text>
      </Pressable>
    );
  };

  if (!permission) {
    return <View style={styles.fill} />;
  }

  if (!permission.granted) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]} testID="incident-capture-screen">
        <ScreenHeader title={t(def.tKey)} />
        <View style={styles.permissionWrap} testID="incident-camera-permission">
          <View style={styles.permissionIcon}>
            <CameraIcon size={40} color={colors.primary} strokeWidth={2} />
          </View>
          <Text style={styles.permissionTitle}>{t("incident.cameraPermissionTitle")}</Text>
          <Text style={styles.permissionBody}>{t("incident.cameraPermissionBody")}</Text>
          {permission.canAskAgain ? (
            <BigButton
              testID="incident-grant-camera-button"
              label={t("incident.cameraPermissionTitle")}
              icon={CameraIcon}
              onPress={() => void requestPermission()}
            />
          ) : (
            <>
              <Text style={styles.permissionBody}>{t("errors.cameraDenied")}</Text>
              <BigButton
                testID="incident-open-settings-button"
                label={t("common.openSettings")}
                icon={Settings}
                variant="outline"
                onPress={() => void Linking.openSettings()}
              />
            </>
          )}
        </View>
      </SafeAreaView>
    );
  }

  // ---- Tap 2: camera ----
  if (!shot) {
    return (
      <View style={styles.fill} testID="incident-capture-screen">
        <CameraView ref={cameraRef} style={styles.fill} facing="back" />
        <SafeAreaView style={styles.cameraOverlay}>
          <View style={styles.cameraTop}>
            <View style={styles.catChip}>
              <CatIcon size={18} color="#FFFFFF" strokeWidth={2.4} />
              <Text style={styles.catChipText}>{t(def.tKey)}</Text>
            </View>
            {gpsChip()}
          </View>
          <View style={styles.shutterRow}>
            <Pressable
              testID="incident-shutter-button"
              accessibilityRole="button"
              onPress={() => void capture()}
              style={({ pressed }) => [styles.shutter, { opacity: pressed || capturing ? 0.7 : 1 }]}
            >
              <View style={styles.shutterInner} />
            </Pressable>
          </View>
        </SafeAreaView>
      </View>
    );
  }

  // ---- Tap 3: watermark preview + submit ----
  const displayW = windowW - sizes.screenPadding * 2;
  const displayH = Math.round((displayW * shot.height) / shot.width);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="incident-preview-screen">
      <ScreenHeader title={t("incident.preview")} />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView contentContainerStyle={styles.previewScroll} keyboardShouldPersistTaps="handled">
          <View
            ref={watermarkRef}
            collapsable={false}
            style={[styles.shotWrap, { width: displayW, height: displayH }]}
          >
            <Image source={{ uri: shot.uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
            <View style={styles.watermark} testID="incident-watermark">
              <Text style={styles.wmLine1}>HOGO PLUS · {t(def.tKey)}</Text>
              <Text style={styles.wmLine2}>
                {dayjs(capturedAt).format("DD/MM/YYYY HH:mm")} ·{" "}
                {gps ? `${gps.lat.toFixed(5)}, ${gps.lng.toFixed(5)}` : t("incident.gpsNone")}
              </Text>
              <Text style={styles.wmLine2}>
                {profile?.full_name ?? ""}{profile?.emp_id ? ` · ${profile.emp_id}` : ""}
              </Text>
            </View>
          </View>

          <Text style={styles.fieldLabel}>{t("incident.aboutDept")}</Text>
          <Pressable
            testID="incident-dept-selector"
            accessibilityRole="button"
            onPress={() => setDeptModal(true)}
            style={styles.deptRow}
          >
            <Text style={styles.deptText} numberOfLines={1}>
              {selectedDept
                ? tri(selectedDept as unknown as Record<string, unknown>, "name")
                : dept}
            </Text>
            <ChevronDown size={22} color={colors.muted} strokeWidth={2.4} />
          </Pressable>

          <Text style={styles.fieldLabel}>{t("incident.descriptionOptional")}</Text>
          <TextInput
            testID="incident-desc-input"
            style={styles.descInput}
            value={desc}
            onChangeText={setDesc}
            placeholder={t("incident.descriptionHint")}
            placeholderTextColor={colors.muted}
            multiline
            maxLength={500}
          />

          <View style={styles.actions}>
            <BigButton
              testID="incident-retake-button"
              label={t("reg.retake")}
              icon={RefreshCcw}
              variant="muted"
              disabled={submitting}
              onPress={() => setShot(null)}
              style={{ flex: 1 }}
            />
            <BigButton
              testID="submit-incident-button"
              label={t("incident.submitIncident")}
              variant="danger"
              loading={submitting}
              onPress={() => void submit()}
              height={64}
              style={{ flex: 2 }}
            />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      <Modal visible={deptModal} transparent animationType="slide" onRequestClose={() => setDeptModal(false)}>
        <Pressable style={styles.modalBackdrop} onPress={() => setDeptModal(false)}>
          <View style={styles.modalSheet} testID="incident-dept-modal">
            <Text style={styles.modalTitle}>{t("incident.aboutDept")}</Text>
            <FlatList
              data={departments.data ?? []}
              keyExtractor={(d) => d.code}
              renderItem={({ item }) => {
                const Icon = departmentIcon(item.code);
                const active = item.code === dept;
                return (
                  <Pressable
                    testID={`incident-dept-${item.code}`}
                    onPress={() => {
                      setDept(item.code);
                      setDeptModal(false);
                    }}
                    style={[styles.modalRow, active && styles.modalRowActive]}
                  >
                    <Icon size={24} color={active ? colors.primary : colors.muted} strokeWidth={2.2} />
                    <Text style={[styles.modalRowText, active && { color: colors.primary }]}>
                      {tri(item as unknown as Record<string, unknown>, "name")}
                    </Text>
                  </Pressable>
                );
              }}
            />
          </View>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  fill: { flex: 1, backgroundColor: "#000000" },
  cameraOverlay: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: "space-between",
    pointerEvents: "box-none",
  },
  cameraTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: sizes.screenPadding,
    gap: spacing.sm,
  },
  cameraClose: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
  },
  cameraCloseText: { fontFamily: fonts.bold, fontSize: 24, color: "#FFFFFF" },
  catChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(0,0,0,0.6)",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  catChipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
  gpsChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(0,0,0,0.6)",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 36,
  },
  gpsChipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
  shutterRow: { alignItems: "center", paddingBottom: spacing.xl },
  shutter: {
    width: sizes.cameraShutter,
    height: sizes.cameraShutter,
    borderRadius: sizes.cameraShutter / 2,
    borderWidth: 5,
    borderColor: "#FFFFFF",
    alignItems: "center",
    justifyContent: "center",
  },
  shutterInner: {
    width: sizes.cameraShutter - 20,
    height: sizes.cameraShutter - 20,
    borderRadius: (sizes.cameraShutter - 20) / 2,
    backgroundColor: colors.danger,
  },
  permissionWrap: {
    flex: 1,
    justifyContent: "center",
    padding: sizes.screenPadding,
    gap: spacing.lg,
  },
  permissionIcon: {
    alignSelf: "center",
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  permissionTitle: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
    textAlign: "center",
  },
  permissionBody: {
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
    textAlign: "center",
  },
  previewScroll: { padding: sizes.screenPadding, gap: spacing.sm, paddingBottom: spacing.xxl },
  shotWrap: {
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: "#000000",
    justifyContent: "flex-end",
  },
  watermark: {
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: 1,
  },
  wmLine1: { fontFamily: fonts.bold, fontSize: 15, color: "#FFFFFF" },
  wmLine2: { fontFamily: fonts.medium, fontSize: 13, color: "#FFFFFF" },
  fieldLabel: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.text,
    marginTop: spacing.md,
  },
  deptRow: {
    height: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
  },
  deptText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text, flex: 1 },
  descInput: {
    minHeight: 72,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    textAlignVertical: "top",
  },
  actions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.lg },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "flex-end",
  },
  modalSheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: sizes.screenPadding,
    maxHeight: "70%",
    gap: spacing.sm,
  },
  modalTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, marginBottom: spacing.sm },
  modalRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
  },
  modalRowActive: { backgroundColor: colors.brandTertiary },
  modalRowText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
});
