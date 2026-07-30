import dayjs from "dayjs";
import { CameraView, useCameraPermissions, useMicrophonePermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useVideoPlayer, VideoView } from "expo-video";
import NetInfo from "@react-native-community/netinfo";
import {
  Camera as CameraIcon,
  ChevronDown,
  Maximize2,
  MapPin,
  MapPinOff,
  Play,
  Settings,
  Sparkles,
  Video as VideoIcon,
  X,
} from "lucide-react-native";
import React, { useEffect, useRef, useState } from "react";
import {
  FlatList,
  Image,
  Linking,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, localizedDetail, uploadFile } from "@/src/api/client";
import { aiVoiceDescribe, createIncident, listDepartments } from "@/src/api/endpoints";
import type { DepartmentItem, Incident } from "@/src/api/types";
import { beaconPayload, type BleBeaconHit } from "@/src/ble/BleScanner";
import { startZoneSession } from "@/src/ble/zoneSession";
import { BigButton } from "@/src/components/BigButton";
import { CaptureGuards } from "@/src/components/CaptureGuards";
import { EyeLoader } from "@/src/components/EyeLoader";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { departmentIcon } from "@/src/constants/departments";
import { VoiceFieldInput } from "@/src/forms/fields/VoiceFieldInput";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import i18n, { tri } from "@/src/i18n";
import { useOutboxStore } from "@/src/offline/outbox";
import { storage } from "@/src/utils/storage";
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

/** Inline video preview (expo-video); controls=false renders a plain thumbnail surface. */
function VideoPreviewCard({ uri, controls = true }: { uri: string; controls?: boolean }) {
  const player = useVideoPlayer(uri, (p) => {
    p.loop = false;
  });
  return (
    <VideoView
      player={player}
      style={StyleSheet.absoluteFill}
      nativeControls={controls}
      contentFit={controls ? "contain" : "cover"}
    />
  );
}

/** Photo-first complaint flow: camera opens immediately, GPS acquired in
 * parallel, then one detail screen (photo, description, voice note) → submit.
 * Category defaults to 'other' — the AI suggestion is confirmed post-submit. */
export default function IncidentCapture() {
  // Launch order 2026-07-27 (C1): SAME strict guards as punch — camera, location
  // permission, GPS on, Bluetooth on + Nearby-devices permission. No Continue-anyway.
  return (
    <CaptureGuards camera location gps bluetooth strict>
      <IncidentCaptureInner />
    </CaptureGuards>
  );
}

function IncidentCaptureInner() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const enqueue = useOutboxStore((s) => s.enqueue);
  const { width: windowW, height: windowH } = useWindowDimensions();

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
  // Prompt 16: one-time camera coach overlay (AsyncStorage flag)
  const [coach, setCoach] = useState(false);
  useEffect(() => {
    void storage.getItem<string>("hogo.coach.incidentCamera", "").then((v) => {
      if (!v) setCoach(true);
    });
  }, []);
  const dismissCoach = () => {
    setCoach(false);
    void storage.setItem("hogo.coach.incidentCamera", "1");
  };
  const [desc, setDesc] = useState("");
  const [voiceUri, setVoiceUri] = useState<string | undefined>(undefined);
  // v1.0.21 voice-first: record → upload → Whisper STT → AI writes the description
  const [transcribing, setTranscribing] = useState(false);
  const [aiWrote, setAiWrote] = useState(false);
  const voiceKeyRef = useRef<string | null>(null);
  const [deptModal, setDeptModal] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const cameraRef = useRef<CameraView>(null);
  const watermarkRef = useRef<View>(null);
  const recordTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  // BLE zone context: scanned in the BACKGROUND while the camera is open. The user
  // never waits on it — whatever is found by Submit time travels with the payload.
  const bleHitRef = useRef<BleBeaconHit | null>(null);
  // v1.0.15: matched zone label (user's language) for the live "📍 zone" chip.
  const [bleZone, setBleZone] = useState<string | null>(null);

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

  // Background BLE zone scan (non-blocking, dual-mode). Optional context only —
  // any failure/timeout is silently ignored and the incident submits beacon=null.
  // v1.0.17: EXACT same code path as the punch flow — shared ZoneSession (cached
  // registry, successive 5s LOW_LATENCY windows for up to 60s, early exit on match).
  // The v1.0.16 single mount-time 10s window competed with camera init and never
  // retried, which is why incidents shipped without a zone even when punch matched.
  useEffect(() => {
    const session = startZoneSession();
    const off = session.onUpdate(() => {
      bleHitRef.current = session.getHit();
      setBleZone(session.getZone());
    });
    return () => {
      off();
      session.stop();
    };
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

  /** Voice-first: transcribe as soon as a note is recorded. NEVER a dead end —
   * any failure keeps the note attached (the server writes the description
   * after submit) and typing stays available throughout. */
  const transcribeVoice = async (uri: string) => {
    if (!online) {
      showToast(t("voice.willTranscribeLater"), "info");
      return;
    }
    setTranscribing(true);
    try {
      const up = await uploadFile(uri, "voice_note.m4a");
      voiceKeyRef.current = up.key;
      const res = await aiVoiceDescribe(up.key);
      if (res.description) {
        setDesc(res.description);
        setAiWrote(true);
      } else {
        showToast(t("voice.nothingHeard"), "info");
      }
    } catch (e) {
      const msg = localizedDetail(e, i18n.language || "en");
      const isCap = e instanceof ApiError && e.status === 429;
      showToast(msg ?? t("voice.willTranscribeLater"), isCap ? "error" : "info");
    } finally {
      setTranscribing(false);
    }
  };

  const onVoiceChange = (uri: string | undefined) => {
    setVoiceUri(uri);
    voiceKeyRef.current = null;
    if (uri) void transcribeVoice(uri);
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
      // offline outbox idempotency: replays of this report return the same incident
      client_uuid: `inc-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      ...beaconPayload(bleHitRef.current),
    };
    // voice note already uploaded during transcription — reuse the key
    if (voiceKeyRef.current) payload.voice_note_key = voiceKeyRef.current;

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
        if (voiceUri && !voiceKeyRef.current) {
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

    // ---- photo path: optimistic — always via the outbox ----
    let finalUri: string;
    try {
      finalUri = await buildFinalImage();
    } catch (err) {
      console.warn("buildFinalImage failed:", err);
      showToast(t("errors.generic"), "error");
      setSubmitting(false);
      return;
    }
    // Queue locally + upload in the background: the user is unblocked immediately;
    // the outbox worker handles retries and the success screen shows live progress.
    const oid = await enqueue({
      type: "incident",
      payload,
      photoUri: finalUri,
      photoName: "incident.jpg",
      photoField: "photo_key",
      files:
        voiceUri && !voiceKeyRef.current
          ? [{ field: "voice_note_key", uri: voiceUri, name: "voice_note.m4a", kind: "audio" }]
          : undefined,
    });
    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
    router.replace({ pathname: "/incident/success", params: { oid } });
  };

  const gpsChip = () => {
    if (gpsStatus === "searching") {
      return (
        <View style={styles.gpsChip} testID="gps-chip-searching">
          <EyeLoader size={16} />
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
          videoBitrate={2_000_000}
        />
        {coach ? (
          <View style={styles.coachWrap} testID="camera-coach-overlay">
            <View style={styles.coachCard}>
              <View style={styles.coachSteps}>
                <Text style={styles.coachStep}>📷 {t("coach.photo")}</Text>
                <Text style={styles.coachArrow}>→</Text>
                <Text style={styles.coachStep}>🎙 {t("coach.speak")}</Text>
                <Text style={styles.coachArrow}>→</Text>
                <Text style={styles.coachStep}>✅ {t("coach.send")}</Text>
              </View>
              <BigButton
                testID="camera-coach-gotit"
                label={t("coach.gotIt")}
                height={52}
                onPress={dismissCoach}
              />
            </View>
          </View>
        ) : null}
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
            {bleZone ? (
              <View style={[styles.gpsChip, { backgroundColor: colors.primary }]} testID="zone-chip">
                <Text style={styles.gpsChipText}>📍 {bleZone}</Text>
              </View>
            ) : null}
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

  // ---- Tap 2: details + submit (compact — the whole core path fits without scrolling) ----
  const displayW = windowW - sizes.screenPadding * 2;
  // off-screen full-aspect view used ONLY for the watermark burn-in (photo quality unchanged)
  const burnH = shot ? Math.round((displayW * shot.height) / shot.width) : 0;
  // visible media card: ~24% of screen height, tap to view full-screen
  const mediaH = Math.round(windowH * 0.24);

  const locationLine = () => {
    if (gpsStatus === "searching") {
      return (
        <View style={styles.locLine} testID="capture-location-line">
          <EyeLoader size={16} />
          <Text style={styles.locText} numberOfLines={1}>{t("incident.gpsSearching")}</Text>
        </View>
      );
    }
    if (gps) {
      return (
        <View style={styles.locLine} testID="capture-location-line">
          <MapPin size={18} color={colors.success} strokeWidth={2.4} />
          <Text style={styles.locText} numberOfLines={1}>
            {bleZone ? `📍 ${bleZone} · ` : ""}
            {address ?? `${gps.lat.toFixed(5)}, ${gps.lng.toFixed(5)}`}
          </Text>
        </View>
      );
    }
    return (
      <Pressable
        testID="capture-location-line"
        onPress={() => {
          if (gpsStatus === "blocked") void Linking.openSettings();
        }}
        style={styles.locLine}
      >
        <MapPinOff size={18} color={colors.warning} strokeWidth={2.4} />
        <Text style={[styles.locText, { color: colors.warning }]} numberOfLines={1}>
          {gpsStatus === "blocked" ? t("common.openSettings") : t("incident.gpsNone")}
        </Text>
      </Pressable>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="incident-preview-screen">
      <ScreenHeader title={t("incident.preview")} />
      <KeyboardAwareScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.previewScroll}
        keyboardShouldPersistTaps="handled"
        bottomOffset={24}
      >
          {/* off-screen full-size composite for the burn-in — never visible */}
          {shot ? (
            <View
              ref={watermarkRef}
              collapsable={false}
              style={[styles.burnSource, { width: displayW, height: burnH }]}
            >
              <Image source={{ uri: shot.uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
              <View style={styles.watermark}>
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
          ) : null}

          {/* compact media card — tap opens the full-screen viewer */}
          <Pressable
            testID="incident-media-card"
            accessibilityRole="button"
            onPress={() => setViewerOpen(true)}
            style={[styles.mediaCard, { height: mediaH }]}
          >
            {videoUri ? (
              <>
                <VideoPreviewCard uri={videoUri} controls={false} />
                <View style={styles.playOverlay}>
                  <Play size={34} color="#FFFFFF" strokeWidth={2.4} fill="#FFFFFF" />
                </View>
              </>
            ) : (
              <Image source={{ uri: shot!.uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
            )}
            <View style={styles.mediaStrip} testID="incident-watermark">
              <Text style={styles.mediaStripText} numberOfLines={1}>
                {videoUri ? "🎬 " : ""}{dayjs(capturedAt).format("DD/MM HH:mm")} · {profile?.full_name ?? ""}
              </Text>
            </View>
            <View style={styles.expandBadge}>
              <Maximize2 size={18} color="#FFFFFF" strokeWidth={2.6} />
            </View>
          </Pressable>

          {locationLine()}

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

          {/* v1.0.21 voice-first: speaking is the PRIMARY input; typing is optional */}
          <View style={styles.voiceHeadRow}>
            <Text style={styles.voiceHeadText}>🎙 {t("voice.speakFirst")}</Text>
            {aiWrote ? (
              <View style={styles.aiChip} testID="voice-ai-chip">
                <Sparkles size={14} color={colors.primary} strokeWidth={2.4} />
                <Text style={styles.aiChipText}>AI</Text>
              </View>
            ) : null}
          </View>
          <VoiceFieldInput value={voiceUri} onChange={onVoiceChange} testID="incident-voice-note" />
          {transcribing ? (
            <View style={styles.transcribingRow} testID="voice-transcribing">
              <EyeLoader size={16} />
              <Text style={styles.transcribingText}>{t("voice.transcribing")}</Text>
            </View>
          ) : null}

          <TextInput
            testID="incident-desc-input"
            style={styles.descInput}
            value={desc}
            onChangeText={(v) => {
              setDesc(v);
              setAiWrote(false); // manual edit clears the AI chip — never locks
            }}
            placeholder={t("voice.typeOptional")}
            placeholderTextColor={colors.muted}
            multiline
            maxLength={500}
          />

          <View style={styles.actions}>
            <BigButton
              testID="incident-retake-button"
              label={t("reg.retake")}
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
              height={60}
              style={{ flex: 2 }}
            />
          </View>
      </KeyboardAwareScrollView>

      {/* full-screen media viewer */}
      <Modal visible={viewerOpen} animationType="fade" onRequestClose={() => setViewerOpen(false)}>
        <View style={styles.viewerWrap} testID="incident-media-viewer">
          {videoUri ? (
            <VideoPreviewCard uri={videoUri} controls />
          ) : shot ? (
            <Image source={{ uri: shot.uri }} style={StyleSheet.absoluteFill} resizeMode="contain" />
          ) : null}
          <SafeAreaView style={[styles.viewerClose, { pointerEvents: "box-none" }]}>
            <Pressable
              testID="viewer-close-button"
              accessibilityRole="button"
              onPress={() => setViewerOpen(false)}
              style={styles.cameraClose}
            >
              <X size={26} color="#FFFFFF" strokeWidth={2.6} />
            </Pressable>
          </SafeAreaView>
        </View>
      </Modal>

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
  coachWrap: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.65)",
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    zIndex: 50,
    elevation: 50,
  },
  coachCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.lg,
    width: "100%",
    maxWidth: 420,
  },
  coachSteps: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  coachStep: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  coachArrow: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.primary },
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
  previewScroll: { padding: sizes.screenPadding, gap: spacing.sm, paddingBottom: spacing.lg },
  burnSource: { position: "absolute", left: -10000, top: 0, justifyContent: "flex-end" },
  mediaCard: {
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: "#000000",
    justifyContent: "flex-end",
  },
  mediaStrip: {
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
  },
  mediaStripText: { fontFamily: fonts.medium, fontSize: 12, color: "#FFFFFF" },
  expandBadge: {
    position: "absolute",
    top: spacing.sm,
    right: spacing.sm,
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
  },
  playOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
  },
  viewerWrap: { flex: 1, backgroundColor: "#000000" },
  viewerClose: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "flex-start",
    padding: sizes.screenPadding,
  },
  locLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: 28,
  },
  locText: { flex: 1, fontFamily: fonts.medium, fontSize: type.sm, color: colors.text },
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
    minHeight: 64,
    maxHeight: 84,
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
  actions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xs },
  voiceHeadRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.xs,
  },
  voiceHeadText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  aiChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 3,
  },
  aiChipText: { fontFamily: fonts.bold, fontSize: 12, color: colors.primary },
  transcribingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: 24,
  },
  transcribingText: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.primary },
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
