import * as Clipboard from "expo-clipboard";
import { useLocalSearchParams } from "expo-router";
import { Camera as CameraIcon, Car, CircleDot, Clock, Copy, MapPin, Smartphone } from "lucide-react-native";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, fileUrl, uploadFile } from "@/src/api/client";
import { changeIncidentStatus, incidentDetail } from "@/src/api/endpoints";
import type { IncidentDetail, TimelineEntry } from "@/src/api/types";
import { AudioPlayerCard } from "@/src/components/AudioPlayerCard";
import { BigButton } from "@/src/components/BigButton";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { EscalateModal } from "@/src/components/EscalateModal";
import { EyeLoader } from "@/src/components/EyeLoader";
import { MediaCard } from "@/src/components/MediaCard";
import { PhotoCaptureModal } from "@/src/components/PhotoCaptureModal";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { SeverityChip } from "@/src/components/SeverityChip";
import { showToast } from "@/src/components/Toast";
import { StatusChip } from "@/src/components/StatusChip";
import { categoryDef } from "@/src/constants/categories";
import { useApprovalsStore } from "@/src/stores/approvalsStore";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, statusColors, type } from "@/src/theme/tokens";
import { formatDateTime } from "@/src/utils/format";

export default function IncidentDetailScreen() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const profile = useAuthStore((s) => s.profile);
  const rank = profile?.role?.rank ?? 6;
  const adjustApprovals = useApprovalsStore((s) => s.adjust);

  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [acting, setActing] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [note, setNote] = useState("");
  const [resolutionUri, setResolutionUri] = useState<string | null>(null);
  const [photoModal, setPhotoModal] = useState(false);
  const [escalateOpen, setEscalateOpen] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setFailed(false);
    try {
      setDetail(await incidentDetail(id));
    } catch {
      setFailed(true);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // AI severity + ANPR land async — re-poll lightly (max 5x) while either is pending
  const pollCount = useRef(0);
  useEffect(() => {
    if (!detail) return;
    const waiting = !detail.severity_reason || detail.plate_status === "pending";
    if (!waiting || pollCount.current >= 5) return;
    const timer = setTimeout(() => {
      pollCount.current += 1;
      void load();
    }, 8000);
    return () => clearTimeout(timer);
  }, [detail, load]);

  const act = async (status: string, actionNote?: string, resolutionPhotoKey?: string) => {
    if (!id || acting) return;
    setActing(true);
    try {
      await changeIncidentStatus(id, status, actionNote, resolutionPhotoKey);
      if (detail && (detail.status === "submitted" || detail.status === "escalated")) {
        adjustApprovals("incidents", -1);
      }
      setResolving(false);
      setNote("");
      setResolutionUri(null);
      await load();
      showToast(t("common.done"), "success");
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) showToast(t("errors.generic"), "error");
      else if (e instanceof ApiError && e.status === 400) {
        showToast(t("reports.resolutionPhotoRequired"), "error");
      } else if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else showToast(t("errors.server"), "error");
    } finally {
      setActing(false);
    }
  };

  /** Resolution photo is mandatory: upload it, then mark resolved. */
  const resolveWithPhoto = async () => {
    if (!resolutionUri || acting) return;
    setActing(true);
    try {
      const uploaded = await uploadFile(resolutionUri, "resolution.jpg");
      setActing(false);
      await act("resolved", note.trim() || undefined, uploaded.key);
    } catch (e) {
      setActing(false);
      showToast(e instanceof ApiError && e.status === 0 ? t("errors.network") : t("errors.uploadFailed"), "error");
    }
  };

  const timelineLabel = (entry: TimelineEntry): string => {
    const to = entry.detail_json?.to;
    if (typeof to === "string") return t(`status.${to}`);
    if (entry.event === "seen") return t("status.seen");
    if (entry.event === "escalated") return t("status.escalated");
    return t("status.submitted");
  };

  const def = detail ? categoryDef(detail.category) : null;
  const CatIcon = def?.icon ?? CircleDot;

  const PLATE_REASON_KEY: Record<string, string> = {
    no_text_found: "incident.reasonNoText",
    no_valid_plate: "incident.reasonNoValidPlate",
    detection_failed: "incident.reasonDetectionFailed",
  };

  const copyPlate = async () => {
    if (!detail?.detected_plate) return;
    try {
      await Clipboard.setStringAsync(detail.detected_plate);
      showToast(t("incident.copied"), "success");
    } catch {
      showToast(t("errors.generic"), "error");
    }
  };

  const plateDetected =
    detail?.detected_plate && (detail.plate_status === "detected" || !detail.plate_status);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="incident-detail-screen">
      <ScreenHeader title={def ? t(def.tKey) : t("reports.title")} />
      {failed ? (
        <ErrorRetry onRetry={() => void load()} />
      ) : !detail ? (
        <View style={styles.loading}>
          <EyeLoader size={40} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {detail.video_key || detail.photo_key ? (
            <View testID="incident-media-card">
              <MediaCard
                uri={fileUrl((detail.video_key ?? detail.photo_key) as string)}
                kind={detail.video_key ? "video" : "photo"}
                height={220}
                testID="incident-media"
              />
              <View style={styles.mediaBadge}>
                <StatusChip status={detail.status} />
              </View>
            </View>
          ) : null}
          <View style={styles.headRow}>
            <View style={[styles.catIcon, { backgroundColor: `${def?.tint ?? colors.muted}18` }]}>
              <CatIcon size={26} color={def?.tint ?? colors.muted} strokeWidth={2.2} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.catTitle}>{def ? t(def.tKey) : detail.category}</Text>
              <Text style={styles.meta}>{formatDateTime(detail.created_at)}</Text>
            </View>
            <View style={{ alignItems: "flex-end", gap: 4 }}>
              {!detail.video_key && !detail.photo_key ? <StatusChip status={detail.status} /> : null}
              <SeverityChip severity={detail.severity} testID="incident-severity-chip" />
            </View>
          </View>

          {plateDetected ? (
            <View style={styles.plateCard} testID="incident-plate-card">
              <View style={styles.plateHeader}>
                <Car size={18} color={colors.primary} strokeWidth={2.4} />
                <Text style={styles.plateLabel}>{t("incident.detectedPlate")}</Text>
              </View>
              <View style={styles.plateRow}>
                <Text style={styles.plateBig} testID="incident-plate-text">
                  {detail.detected_plate}
                </Text>
                <Pressable
                  style={({ pressed }) => [styles.copyBtn, pressed && { opacity: 0.6 }]}
                  onPress={() => void copyPlate()}
                  testID="copy-plate-button"
                >
                  <Copy size={16} color={colors.primary} strokeWidth={2.2} />
                  <Text style={styles.copyText}>{t("incident.copy")}</Text>
                </Pressable>
              </View>
              {detail.plate_confidence != null ? (
                <Text style={styles.plateMeta}>
                  {t("incident.confidence")}: {Math.round(detail.plate_confidence)}%
                </Text>
              ) : null}
            </View>
          ) : detail.plate_status === "pending" ? (
            <View style={styles.plateCard} testID="incident-plate-pending">
              <View style={styles.plateHeader}>
                <EyeLoader size={16} />
                <Text style={styles.plateLabel}>{t("incident.plateChecking")}</Text>
              </View>
            </View>
          ) : detail.plate_status === "not_detected" ? (
            <View style={[styles.plateCard, styles.plateMissCard]} testID="incident-plate-missing">
              <View style={styles.plateHeader}>
                <Car size={18} color={colors.warning} strokeWidth={2.4} />
                <Text style={styles.plateMissTitle}>{t("incident.plateNotDetected")}</Text>
              </View>
              {detail.plate_reason ? (
                <Text style={styles.plateMeta}>
                  {t(PLATE_REASON_KEY[detail.plate_reason] ?? "incident.reasonNoValidPlate")}
                </Text>
              ) : null}
            </View>
          ) : null}

          {detail.ble_zone || detail.address_text || detail.gps_lat != null ? (
            <>
              <View style={styles.locationBlock} testID="incident-object-location">
                <View style={styles.locationRow}>
                  <MapPin size={18} color={colors.primary} strokeWidth={2.4} />
                  <Text style={styles.locationLabel}>{t("incident.objectLocation")}</Text>
                </View>
                {detail.ble_zone ? (
                  <Text style={styles.locationAddress} testID="incident-beacon-zone">
                    📍 {t("incident.beaconZone")}: {detail.ble_zone}
                  </Text>
                ) : null}
                {detail.address_text ? (
                  <Text style={styles.locationAddress}>{detail.address_text}</Text>
                ) : null}
                {detail.gps_lat != null && detail.gps_lng != null ? (
                  <Text style={styles.locationCoords}>
                    {detail.gps_lat.toFixed(5)}, {detail.gps_lng.toFixed(5)}
                  </Text>
                ) : null}
              </View>
              <View style={styles.locationBlock} testID="incident-device-location">
                <View style={styles.locationRow}>
                  <Smartphone size={18} color={colors.accent} strokeWidth={2.4} />
                  <Text style={styles.locationLabel}>{t("incident.deviceLocation")}</Text>
                </View>
                {detail.address_text ? (
                  <Text style={styles.locationAddress}>{detail.address_text}</Text>
                ) : null}
                {detail.gps_lat != null && detail.gps_lng != null ? (
                  <Text style={styles.locationCoords}>
                    {detail.gps_lat.toFixed(5)}, {detail.gps_lng.toFixed(5)}
                  </Text>
                ) : null}
              </View>
            </>
          ) : null}

          <View style={styles.capturedRow} testID="incident-captured-at">
            <Clock size={15} color={colors.muted} strokeWidth={2.2} />
            <Text style={styles.capturedText}>
              {t("incident.capturedAt")}: {formatDateTime(detail.created_at)}
            </Text>
          </View>

          {detail.severity_reason ? (
            <View style={[styles.card, detail.severity === "critical" && { borderColor: colors.danger }]}>
              <Text style={styles.sectionLabel}>{t("severity.aiReason")}</Text>
              <Text style={styles.desc}>{detail.severity_reason}</Text>
            </View>
          ) : null}

          {detail.description ? (
            <View style={styles.card}>
              <Text style={styles.desc}>{detail.description}</Text>
            </View>
          ) : null}

          {detail.voice_note_key ? (
            <AudioPlayerCard
              uri={fileUrl(detail.voice_note_key)}
              label={t("incident.voiceNote")}
              testID="incident-voice-player"
            />
          ) : null}

          {detail.resolution_note || detail.resolution_photo_key ? (
            <View style={[styles.card, { borderColor: colors.success }]}>
              <Text style={styles.sectionLabel}>{t("reports.resolutionNote")}</Text>
              {detail.resolution_note ? <Text style={styles.desc}>{detail.resolution_note}</Text> : null}
              {detail.resolution_photo_key ? (
                <MediaCard
                  uri={fileUrl(detail.resolution_photo_key)}
                  height={160}
                  testID="resolution-photo"
                />
              ) : null}
            </View>
          ) : null}

          <Text style={styles.sectionTitle}>{t("reports.timeline")}</Text>
          <View style={styles.timeline}>
            {detail.timeline.map((entry) => (
              <View key={entry.id} style={styles.timelineRow} testID={`timeline-${entry.id}`}>
                <View
                  style={[
                    styles.timelineDot,
                    {
                      backgroundColor:
                        statusColors[String(entry.detail_json?.to ?? "submitted")] ?? colors.accent,
                    },
                  ]}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.timelineEvent}>{timelineLabel(entry)}</Text>
                  <Text style={styles.timelineTime}>{formatDateTime(entry.created_at)}</Text>
                </View>
              </View>
            ))}
          </View>

          {rank <= 3 && detail.status !== "resolved" ? (
            <View style={styles.actions}>
              {detail.status === "submitted" ? (
                <BigButton
                  testID="mark-seen-button"
                  label={t("reports.markSeen")}
                  variant="accent"
                  loading={acting}
                  onPress={() => void act("seen")}
                />
              ) : null}
              {detail.status === "seen" ? (
                <BigButton
                  testID="mark-in-progress-button"
                  label={t("reports.markInProgress")}
                  variant="primary"
                  loading={acting}
                  onPress={() => void act("in_progress")}
                />
              ) : null}
              {detail.status !== "submitted" && !resolving ? (
                <BigButton
                  testID="mark-resolved-button"
                  label={t("reports.markResolved")}
                  variant="success"
                  onPress={() => setResolving(true)}
                />
              ) : null}
              {resolving ? (
                <View style={styles.resolveBox}>
                  <Text style={styles.sectionLabel}>{t("reports.resolutionNote")}</Text>
                  <TextInput
                    testID="resolution-note-input"
                    style={styles.noteInput}
                    value={note}
                    onChangeText={setNote}
                    placeholder={t("reports.resolutionNote")}
                    placeholderTextColor={colors.muted}
                    multiline
                  />
                  <Text style={styles.sectionLabel}>{t("reports.resolutionPhoto")}</Text>
                  {resolutionUri ? (
                    <Image
                      source={{ uri: resolutionUri }}
                      style={styles.resolutionPhoto}
                      resizeMode="cover"
                      testID="resolution-photo-preview"
                    />
                  ) : (
                    <Text style={styles.photoRequiredHint}>{t("reports.resolutionPhotoRequired")}</Text>
                  )}
                  <BigButton
                    testID="take-resolution-photo-button"
                    label={t("reports.takeResolutionPhoto")}
                    icon={CameraIcon}
                    variant="outline"
                    disabled={acting}
                    onPress={() => setPhotoModal(true)}
                  />
                  <BigButton
                    testID="confirm-resolve-button"
                    label={t("reports.markResolved")}
                    variant="success"
                    loading={acting}
                    disabled={!resolutionUri}
                    onPress={() => void resolveWithPhoto()}
                  />
                </View>
              ) : null}
              {!resolving ? (
                <BigButton
                  testID="escalate-button"
                  label={t("escalate.button")}
                  variant="outline"
                  onPress={() => setEscalateOpen(true)}
                />
              ) : null}
            </View>
          ) : null}
        </ScrollView>
      )}
      <PhotoCaptureModal
        visible={photoModal}
        label={t("reports.resolutionPhoto")}
        onClose={() => setPhotoModal(false)}
        onCaptured={(uri) => {
          setResolutionUri(uri);
          setPhotoModal(false);
        }}
        testIDPrefix="resolution"
      />
      {id ? (
        <EscalateModal
          incidentId={id}
          visible={escalateOpen}
          onClose={() => setEscalateOpen(false)}
          onDone={() => {
            setEscalateOpen(false);
            void load();
          }}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  loading: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.xxl },
  photo: {
    width: "100%",
    aspectRatio: 4 / 3,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  catIcon: {
    width: 48,
    height: 48,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  catTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  meta: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.xs,
  },
  desc: { fontFamily: fonts.regular, fontSize: type.base, color: colors.text },
  sectionLabel: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.muted },
  sectionTitle: {
    fontFamily: fonts.bold,
    fontSize: type.lg,
    color: colors.text,
    marginTop: spacing.sm,
  },
  timeline: { gap: spacing.md },
  timelineRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
  timelineDot: { width: 14, height: 14, borderRadius: 7, marginTop: 5 },
  timelineEvent: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  timelineTime: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  actions: { gap: spacing.md, marginTop: spacing.md },
  resolveBox: { gap: spacing.sm },
  mediaCard: {
    borderRadius: radius.lg,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceTertiary,
  },
  mediaBadge: { position: "absolute", top: spacing.sm, right: spacing.sm },
  plateCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.primary,
    padding: spacing.md,
    gap: spacing.xs,
  },
  plateMissCard: { borderColor: colors.warning, backgroundColor: `${colors.warning}10` },
  plateHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  plateRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  plateBig: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
    letterSpacing: 2,
  },
  copyBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    minHeight: 36,
  },
  copyText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.primary },
  plateLabel: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  plateMeta: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  plateMissTitle: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  capturedRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  capturedText: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  resolutionPhoto: {
    width: "100%",
    aspectRatio: 4 / 3,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceTertiary,
    marginTop: spacing.xs,
  },
  photoRequiredHint: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.warning },
  locationBlock: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: 4,
  },
  locationRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  locationLabel: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.muted },
  locationAddress: { fontFamily: fonts.medium, fontSize: type.base, color: colors.text },
  locationCoords: { fontFamily: fonts.regular, fontSize: 12, color: colors.muted },
  noteInput: {
    minHeight: 64,
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
});
