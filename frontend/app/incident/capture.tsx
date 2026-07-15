import dayjs from "dayjs";
import { CameraView, useCameraPermissions, useMicrophonePermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useVideoPlayer, VideoView } from "expo-video";
import NetInfo from "@react-native-community/netinfo";
import {
  Camera as CameraIcon,
  ChevronDown,
  MapPin,
  MapPinOff,
  RefreshCcw,
  Settings,
  Video as VideoIcon,
  X,
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
import { departmentIcon } from "@/src/constants/departments";
import { VoiceFieldInput } from "@/src/forms/fields/VoiceFieldInput";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import i18n, { tri } from "@/src/i18n";
import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { burnInSafe } from "@/src/utils/burnIn";
import { reverseGeocode } from "@/src/utils/geocode";
import { acquireGps, type GpsFix } from "@/src/utils/gps";

interface Shot {
  uri: string;
  width: number;
  height: number;
}

type GpsStatus = "searching" | "ok" | "none" | "blocked";

/** Inline video preview for the detail card (expo-video). */
function VideoPreviewCard({ uri }: { uri: string }) {
  const player = useVideoPlayer(uri, (p) => {
    p.loop = false;
  });
  return <VideoView player={player} style={StyleSheet.absoluteFill} nativeControls contentFit="cover" />;
}

/** Photo-first complaint flow: camera opens immediately, GPS acquired in
 * parallel, then one detail screen (photo, description, voice note) → submit.
 * Category defaults to 'other' — the AI suggestion is confirmed post-submit. */
export default function IncidentCapture() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const enqueue = useOutboxStore((s) => s.enqueue);
  const { width: windowW } = useWindowDimensions();

  const [permission, requestPermission] = useCameraPermissions();
  const [micPerm, requestMicPerm] = useMicrophonePermissions();
  const [mode, setMode] = useState<"picture" | "video">("picture");
  const [online, setOnline] = useState(true);
  const [recording, setRecording] = useState(false);
  const [recordLeft, setRecordLeft] = useState(30);
  const [videoUri, setVideoUri] = useState<string | null>(null);
  const [shot, setShot] = useState<Shot | null>(null);
  const [capturedAt, setCapturedAt] = useState<number>(0);
  const [capturing, setCapturing] = useState(false);
  const [gps, setGps] = useState<GpsFix | null>(null);
  const [address, setAddress] = useState<string | null>(null);
  const [gpsStatus, setGpsStatus] = useState<GpsStatus>("searching");
  const [dept, setDept] = useState(profile?.department_code ?? "PRODUCTION");
  const [desc, setDesc] = useState("");
  const [voiceUri, setVoiceUri] = useState<string | undefined>(undefined);
  const [deptModal, setDeptModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const cameraRef = useRef<CameraView>(null);
  const watermarkRef = useRef<View>(null);
  const recordTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const departments = useCachedFetch<DepartmentItem[]>("departments", listDepartments);
  const selectedDept = departments.data?.find((d) => d.code === dept) ?? null;

  useEffect(() => {
    let active = true;
    void (async () => {
      const res = await acquireGps(10000);
      if (!active) return;
      setGps(res.fix);
      setGpsStatus(res.fix ? "ok" : res.blocked ? "blocked" : "none");
      if (res.fix) {
        // Part D: reverse-geocode on-device AT CAPTURE TIME (works for offline queueing too)
        const addr = await reverseGeocode(res.fix.lat, res.fix.lng);
        if (active) setAddress(addr);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Part A offline rule: video capture requires network
  useEffect(() => {
    const sub = NetInfo.addEventListener((state) => {
      const ok = state.isConnected !== false;
      setOnline(ok);
      if (!ok) setMode("picture");
    });
    return () => sub();
  }, []);

  useEffect(
    () => () => {
      if (recordTimer.current) clearInterval(recordTimer.current);
    },
    [],
  );

  const close = () => {
    if (recording) cameraRef.current?.stopRecording();
    return router.canGoBack() ? router.back() : router.replace("/");
  };

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

  const startRecording = async () => {
    if (!cameraRef.current || recording) return;
    if (micPerm && !micPerm.granted && micPerm.canAskAgain) {
      await requestMicPerm(); // contextual: first video attempt (recording continues muted if denied)
    }
    setRecording(true);
    setRecordLeft(30);
    recordTimer.current = setInterval(() => {
      setRecordLeft((s) => {
        if (s <= 1) cameraRef.current?.stopRecording(); // 30s auto-stop
        return Math.max(0, s - 1);
      });
    }, 1000);
    try {
      const video = await cameraRef.current.recordAsync({ maxDuration: 30 });
      if (video?.uri) {
        setVideoUri(video.uri);
        setCapturedAt(Date.now());
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => undefined);
      }
    } catch {
      showToast(t("errors.generic"), "error");
    } finally {
      if (recordTimer.current) clearInterval(recordTimer.current);
      setRecording(false);
      setRecordLeft(30);
    }
  };

  const onShutter = () => {
    if (mode === "picture") {
      void capture();
    } else if (recording) {
      cameraRef.current?.stopRecording();
    } else {
      void startRecording();
    }
  };

  /** Burn watermark into pixels via view-shot, then compress. Never throws for a valid shot. */
  const buildFinalImage = async (): Promise<string> => {
    if (!shot) throw new Error("no shot");
    return burnInSafe(watermarkRef, shot.uri, shot.width, shot.height);
  };

  const submit = async () => {
    if ((!shot && !videoUri) || submitting) return;
    setSubmitting(true);
    const payload: Record<string, unknown> = {
      category: "other", // AI suggests the real category post-submit
      department_code: dept,
      gps_lat: gps?.lat ?? null,
      gps_lng: gps?.lng ?? null,
      address_text: address,
      description: desc.trim() || null,
      severity: "normal",
    };

    // ---- video path (network required; no outbox for videos) ----
    if (videoUri) {
      try {
        const FileSystem = await import("expo-file-system/legacy");
        const info = await FileSystem.getInfoAsync(videoUri);
        if (info.exists && (info.size ?? 0) > 40 * 1024 * 1024) {
          showToast(t("incident.videoTooLarge"), "error");
          setSubmitting(false);
          return;
        }
      } catch {
        // size check best-effort; server enforces the 40MB cap anyway
      }
      try {
        if (voiceUri) {
          const audio = await uploadFile(voiceUri, "voice_note.m4a").catch(() => null);
          if (audio) payload.voice_note_key = audio.key;
        }
        const uploaded = await uploadFile(videoUri, "incident.mp4");
        const incident = await createIncident({ ...payload, video_key: uploaded.key }) as Incident;
        void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
        router.replace({ pathname: "/incident/success", params: { queued: "0", rid: incident.id } });
      } catch (e) {
        if (e instanceof ApiError && e.status === 413) {
          const d = e.detail as Record<string, string> | string;
          const lang = (i18n.language || "en") as "en" | "hi" | "mr";
          showToast(typeof d === "object" && d?.en ? (d[lang] ?? d.en) : t("incident.videoTooLarge"), "error");
        } else if (e instanceof ApiError && e.status === 0) {
          showToast(t("incident.videoNeedsNet"), "error");
        } else {
          showToast(t("errors.server"), "error");
        }
        setSubmitting(false);
      }
      return;
    }

    // ---- photo path (full outbox support) ----
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
      if (voiceUri) {
        try {
          const audio = await uploadFile(voiceUri, "voice_note.m4a");
          payload.voice_note_key = audio.key;
        } catch (audioErr) {
          if (audioErr instanceof ApiError && audioErr.status === 0) throw audioErr;
          // non-network audio failure: submit without the voice note
          console.warn("voice note upload failed:", audioErr);
        }
      }
      const uploaded = await uploadFile(finalUri, "incident.jpg");
      const incident = await createIncident({ ...payload, photo_key: uploaded.key }) as Incident;
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      router.replace({ pathname: "/incident/success", params: { queued: "0", rid: incident.id } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        delete payload.voice_note_key;
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
        <ScreenHeader title={t("home.reportIncident")} />
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

  // ---- Tap 1: camera opens immediately ----
  if (!shot && !videoUri) {
    return (
      <View style={styles.fill} testID="incident-capture-screen">
        <CameraView
          ref={cameraRef}
          style={styles.fill}
          facing="back"
          mode={mode}
          videoQuality="720p"
        />
        <SafeAreaView style={styles.cameraOverlay}>
          <View style={styles.cameraTop}>
            <Pressable
              testID="incident-camera-close-button"
              accessibilityRole="button"
              accessibilityLabel={t("common.close")}
              onPress={close}
              style={styles.cameraClose}
            >
              <X size={26} color="#FFFFFF" strokeWidth={2.6} />
            </Pressable>
            {gpsChip()}
          </View>
          <View style={styles.shutterRow}>
            {!recording ? (
              <View style={styles.modeRow}>
                <Pressable
                  testID="mode-photo-button"
                  onPress={() => setMode("picture")}
                  style={[styles.modeChip, mode === "picture" && styles.modeChipActive]}
                >
                  <CameraIcon size={18} color="#FFFFFF" strokeWidth={2.4} />
                  <Text style={styles.modeChipText}>{t("incident.photoMode")}</Text>
                </Pressable>
                <Pressable
                  testID="mode-video-button"
                  disabled={!online}
                  onPress={() => setMode("video")}
                  style={[
                    styles.modeChip,
                    mode === "video" && styles.modeChipActive,
                    !online && { opacity: 0.4 },
                  ]}
                >
                  <VideoIcon size={18} color="#FFFFFF" strokeWidth={2.4} />
                  <Text style={styles.modeChipText}>{t("incident.videoMode")}</Text>
                </Pressable>
              </View>
            ) : null}
            {!online ? (
              <Text style={styles.offlineNote} testID="video-offline-note">
                {t("incident.videoNeedsNet")}
              </Text>
            ) : null}
            <Text style={styles.shutterHint}>
              {recording
                ? t("incident.recordingLeft", { s: recordLeft })
                : mode === "video"
                  ? t("incident.videoHint")
                  : t("incident.captureHint")}
            </Text>
            <Pressable
              testID="incident-shutter-button"
              accessibilityRole="button"
              onPress={onShutter}
              style={({ pressed }) => [
                styles.shutter,
                recording && styles.shutterRecording,
                { opacity: pressed || capturing ? 0.7 : 1 },
              ]}
            >
              {recording ? (
                <>
                  <View style={styles.shutterStop} />
                  <Text style={styles.shutterCount}>{recordLeft}</Text>
                </>
              ) : (
                <View style={[styles.shutterInner, mode === "video" && { borderRadius: 8 }]} />
              )}
            </Pressable>
          </View>
        </SafeAreaView>
      </View>
    );
  }

  // ---- Tap 2: details + submit ----
  const displayW = windowW - sizes.screenPadding * 2;
  const displayH = shot
    ? Math.round((displayW * shot.height) / shot.width)
    : Math.round(displayW * 0.75);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="incident-preview-screen">
      <ScreenHeader title={t("incident.preview")} />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView contentContainerStyle={styles.previewScroll} keyboardShouldPersistTaps="handled">
          {videoUri ? (
            <View style={[styles.shotWrap, { width: displayW, height: displayH }]} testID="incident-video-card">
              <VideoPreviewCard uri={videoUri} />
              <View style={styles.watermark}>
                <Text style={styles.wmLine1}>HOGO PLUS · {t("home.reportIncident")} · 🎬</Text>
                <Text style={styles.wmLine2}>
                  {dayjs(capturedAt).format("DD/MM/YYYY HH:mm")} ·{" "}
                  {address ?? (gps ? `${gps.lat.toFixed(5)}, ${gps.lng.toFixed(5)}` : t("incident.gpsNone"))}
                </Text>
              </View>
            </View>
          ) : (
            <View
              ref={watermarkRef}
              collapsable={false}
              style={[styles.shotWrap, { width: displayW, height: displayH }]}
            >
              <Image source={{ uri: shot!.uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
              <View style={styles.watermark} testID="incident-watermark">
                <Text style={styles.wmLine1}>HOGO PLUS · {t("home.reportIncident")}</Text>
                <Text style={styles.wmLine2}>
                  {dayjs(capturedAt).format("DD/MM/YYYY HH:mm")} ·{" "}
                  {gps ? `${gps.lat.toFixed(5)}, ${gps.lng.toFixed(5)}` : t("incident.gpsNone")}
                </Text>
                {address ? <Text style={styles.wmLine2} numberOfLines={1}>{address}</Text> : null}
                <Text style={styles.wmLine2}>
                  {profile?.full_name ?? ""}{profile?.emp_id ? ` · ${profile.emp_id}` : ""}
                </Text>
              </View>
            </View>
          )}

          <View style={styles.chipRow}>{gpsChip()}</View>
          {address ? (
            <Text style={styles.addressLine} testID="capture-address-line" numberOfLines={2}>
              📍 {address}
            </Text>
          ) : null}

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

          <Text style={styles.fieldLabel}>{t("incident.voiceNote")}</Text>
          <VoiceFieldInput value={voiceUri} onChange={setVoiceUri} testID="incident-voice-note" />

          <View style={styles.actions}>
            <BigButton
              testID="incident-retake-button"
              label={t("reg.retake")}
              icon={RefreshCcw}
              variant="muted"
              disabled={submitting}
              onPress={() => {
                setShot(null);
                setVideoUri(null);
              }}
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
  shutterRow: { alignItems: "center", paddingBottom: spacing.xl, gap: spacing.md },
  modeRow: { flexDirection: "row", gap: spacing.sm },
  modeChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: radius.pill,
    backgroundColor: "rgba(0,0,0,0.5)",
    borderWidth: 2,
    borderColor: "transparent",
    paddingHorizontal: spacing.lg,
    minHeight: 44,
  },
  modeChipActive: { borderColor: "#FFFFFF" },
  modeChipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
  offlineNote: {
    fontFamily: fonts.medium,
    fontSize: type.sm,
    color: "#FFD9A0",
    backgroundColor: "rgba(0,0,0,0.5)",
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  shutterHint: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: "#FFFFFF",
    backgroundColor: "rgba(0,0,0,0.5)",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
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
  shutterRecording: { borderColor: colors.danger },
  shutterStop: {
    width: 30,
    height: 30,
    borderRadius: 6,
    backgroundColor: colors.danger,
  },
  shutterCount: {
    position: "absolute",
    bottom: -30,
    fontFamily: fonts.bold,
    fontSize: type.lg,
    color: "#FFFFFF",
  },
  addressLine: {
    fontFamily: fonts.medium,
    fontSize: type.sm,
    color: colors.muted,
    marginTop: spacing.xs,
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
  chipRow: { flexDirection: "row", marginTop: spacing.sm },
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
