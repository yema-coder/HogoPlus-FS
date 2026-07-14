import { useLocalSearchParams } from "expo-router";
import { CircleDot } from "lucide-react-native";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Image,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, fileUrl } from "@/src/api/client";
import { changeIncidentStatus, incidentDetail } from "@/src/api/endpoints";
import type { IncidentDetail, TimelineEntry } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
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

  const act = async (status: string, actionNote?: string) => {
    if (!id || acting) return;
    setActing(true);
    try {
      await changeIncidentStatus(id, status, actionNote);
      if (detail && (detail.status === "submitted" || detail.status === "escalated")) {
        adjustApprovals("incidents", -1);
      }
      setResolving(false);
      setNote("");
      await load();
      showToast(t("common.done"), "success");
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) showToast(t("errors.generic"), "error");
      else if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else showToast(t("errors.server"), "error");
    } finally {
      setActing(false);
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

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="incident-detail-screen">
      <ScreenHeader title={def ? t(def.tKey) : t("reports.title")} />
      {failed ? (
        <ErrorRetry onRetry={() => void load()} />
      ) : !detail ? (
        <View style={styles.loading}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <Image
            source={{ uri: fileUrl(detail.photo_key) }}
            style={styles.photo}
            resizeMode="cover"
            testID="incident-photo"
          />
          <View style={styles.headRow}>
            <View style={[styles.catIcon, { backgroundColor: `${def?.tint ?? colors.muted}18` }]}>
              <CatIcon size={26} color={def?.tint ?? colors.muted} strokeWidth={2.2} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.catTitle}>{def ? t(def.tKey) : detail.category}</Text>
              <Text style={styles.meta}>{formatDateTime(detail.created_at)}</Text>
            </View>
            <StatusChip status={detail.status} />
          </View>

          {detail.description ? (
            <View style={styles.card}>
              <Text style={styles.desc}>{detail.description}</Text>
            </View>
          ) : null}

          {detail.resolution_note ? (
            <View style={[styles.card, { borderColor: colors.success }]}>
              <Text style={styles.sectionLabel}>{t("reports.resolutionNote")}</Text>
              <Text style={styles.desc}>{detail.resolution_note}</Text>
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
                  <BigButton
                    testID="confirm-resolve-button"
                    label={t("reports.markResolved")}
                    variant="success"
                    loading={acting}
                    onPress={() => void act("resolved", note.trim() || undefined)}
                  />
                </View>
              ) : null}
            </View>
          ) : null}
        </ScrollView>
      )}
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
