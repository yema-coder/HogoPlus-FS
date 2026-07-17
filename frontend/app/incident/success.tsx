import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { CheckCircle2, CloudOff, Home, Sparkles } from "lucide-react-native";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { confirmIncidentRouting, incidentDetail, listDepartments } from "@/src/api/endpoints";
import type { DepartmentItem, Incident } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { EyeLoader } from "@/src/components/EyeLoader";
import { showToast } from "@/src/components/Toast";
import { INCIDENT_CATEGORIES, categoryDef } from "@/src/constants/categories";
import { departmentIcon } from "@/src/constants/departments";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useOutboxStore } from "@/src/offline/outbox";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

const POLL_MS = 3000;
const MAX_POLLS = 12; // ~36s — after that the 10-min server timeout takes over

/** Post-submit screen: success state + AI category/department confirmation card. */
export default function IncidentSuccess() {
  const router = useRouter();
  const { t } = useTranslation();
  const { queued, rid, oid } = useLocalSearchParams<{ queued: string; rid?: string; oid?: string }>();
  const isQueued = queued === "1";

  // Optimistic mode: the report sits in the outbox — watch its background upload live
  const outboxItem = useOutboxStore((s) => (oid ? s.items.find((i) => i.id === oid) : undefined));
  const outboxResult = useOutboxStore((s) => (oid ? s.results[oid] : undefined));
  const effectiveRid = rid ?? (typeof outboxResult === "string" ? outboxResult : undefined);
  const sending = !!oid && !!outboxItem;
  const willRetry = sending && (outboxItem?.retries ?? 0) > 0;
  const uploadFailed = !!oid && !outboxItem && outboxResult === null;

  const [incident, setIncident] = useState<Incident | null>(null);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [editVisible, setEditVisible] = useState(false);
  const [editCat, setEditCat] = useState<string | null>(null);
  const [editDept, setEditDept] = useState<string | null>(null);
  const polls = useRef(0);

  const departments = useCachedFetch<DepartmentItem[]>("departments", listDepartments);

  useEffect(() => {
    void Haptics.notificationAsync(
      isQueued ? Haptics.NotificationFeedbackType.Warning : Haptics.NotificationFeedbackType.Success,
    ).catch(() => undefined);
  }, [isQueued]);

  // queued (offline) → no AI card possible, go home after 4s like before
  useEffect(() => {
    if (!isQueued) return;
    const timer = setTimeout(() => router.replace("/"), 4000);
    return () => clearTimeout(timer);
  }, [isQueued, router]);

  // poll for the async AI suggestion
  useEffect(() => {
    if (isQueued || !effectiveRid || confirmed) return;
    let active = true;
    const tick = async () => {
      polls.current += 1;
      try {
        const detail = await incidentDetail(effectiveRid);
        if (!active) return;
        setIncident(detail);
        if (detail.ai_suggested_category || detail.ai_confirmed_by) return; // stop polling
      } catch {
        // transient — keep polling
      }
      if (!active) return;
      if (polls.current >= MAX_POLLS) {
        setPollTimedOut(true);
        return;
      }
      timer = setTimeout(() => void tick(), POLL_MS);
    };
    let timer = setTimeout(() => void tick(), 1500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [isQueued, effectiveRid, confirmed]);

  const deptName = useCallback(
    (code: string | null | undefined) => {
      const d = departments.data?.find((x) => x.code === code);
      return d ? tri(d as unknown as Record<string, unknown>, "name") : (code ?? "");
    },
    [departments.data],
  );

  const confirm = async (body: { category?: string; department_code?: string } = {}) => {
    if (!effectiveRid || confirming) return;
    setConfirming(true);
    try {
      const updated = await confirmIncidentRouting(effectiveRid, body);
      setIncident(updated);
      setConfirmed(true);
      setEditVisible(false);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      showToast(t("incident.aiRouted", { dept: deptName(updated.department_code) }), "success");
      setTimeout(() => router.replace("/"), 1800);
    } catch {
      showToast(t("errors.server"), "error");
      setConfirming(false);
    }
  };

  const suggestion = incident?.ai_suggested_category && !incident.ai_confirmed_by ? incident : null;
  const suggestionDef = suggestion ? categoryDef(suggestion.ai_suggested_category ?? "other") : null;
  const SugIcon = suggestionDef?.icon ?? Sparkles;
  const showWaiting = !isQueued && !!effectiveRid && !suggestion && !confirmed && !pollTimedOut
    && !incident?.ai_confirmed_by;

  return (
    <SafeAreaView style={styles.safe} testID="incident-success-screen">
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.center}>
          <View
            style={[
              styles.circle,
              { backgroundColor: isQueued || willRetry || uploadFailed ? "#FDF0DC" : "#DDF5E5" },
            ]}
            testID={
              sending
                ? "incident-uploading-icon"
                : isQueued || uploadFailed
                  ? "incident-queued-icon"
                  : "incident-sent-icon"
            }
          >
            {sending && !willRetry ? (
              <EyeLoader size={38} />
            ) : isQueued || willRetry || uploadFailed ? (
              <CloudOff size={56} color={colors.warning} strokeWidth={2} />
            ) : (
              <CheckCircle2 size={56} color={colors.success} strokeWidth={2} />
            )}
          </View>
          <Text style={styles.title}>
            {isQueued || sending
              ? t("incident.queuedTitle")
              : uploadFailed
                ? t("incident.uploadFailed")
                : t("incident.successTitle")}
          </Text>
          <Text style={styles.body}>
            {uploadFailed
              ? t("errors.generic")
              : willRetry
                ? t("incident.willRetryBody")
                : sending
                  ? t("incident.uploadingBody")
                  : isQueued
                    ? t("incident.queuedBody")
                    : t("incident.sentToManager")}
          </Text>
          {!isQueued && effectiveRid ? (
            <Text style={styles.rid} testID="incident-id-text">
              {t("incident.incidentId")}: #{effectiveRid.slice(0, 8).toUpperCase()}
            </Text>
          ) : null}
          {isQueued ? <Text style={styles.returning}>{t("incident.returningHome")}</Text> : null}
        </View>

        {showWaiting ? (
          <View style={styles.waitCard} testID="ai-waiting-card">
            <EyeLoader size={18} />
            <Text style={styles.waitText}>{t("incident.aiWaiting")}</Text>
          </View>
        ) : null}

        {pollTimedOut && !suggestion && !confirmed ? (
          <View style={styles.waitCard} testID="ai-timeout-note">
            <Sparkles size={20} color={colors.muted} strokeWidth={2.2} />
            <Text style={styles.waitText}>{t("incident.aiLater")}</Text>
          </View>
        ) : null}

        {suggestion && !confirmed ? (
          <View style={styles.aiCard} testID="ai-suggestion-card">
            <View style={styles.aiHead}>
              <Sparkles size={20} color={colors.primary} strokeWidth={2.2} />
              <Text style={styles.aiTitle}>{t("incident.aiCardTitle")}</Text>
              {typeof suggestion.ai_confidence === "number" ? (
                <Text style={styles.aiConfidence}>
                  {Math.round(suggestion.ai_confidence * 100)}%
                </Text>
              ) : null}
            </View>
            <View style={styles.aiRow}>
              <View style={[styles.aiIcon, { backgroundColor: `${suggestionDef?.tint ?? colors.muted}18` }]}>
                <SugIcon size={28} color={suggestionDef?.tint ?? colors.muted} strokeWidth={2.2} />
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={styles.aiCat}>{t(suggestionDef?.tKey ?? "cat.other")}</Text>
                <Text style={styles.aiDept} numberOfLines={1}>
                  {deptName(suggestion.ai_suggested_department)}
                </Text>
              </View>
            </View>
            <View style={styles.aiActions}>
              <BigButton
                testID="ai-accept-button"
                label={t("incident.aiAccept")}
                variant="success"
                loading={confirming && !editVisible}
                onPress={() => void confirm()}
                style={{ flex: 1 }}
              />
              <BigButton
                testID="ai-change-button"
                label={t("incident.aiChange")}
                variant="outline"
                disabled={confirming}
                onPress={() => {
                  setEditCat(suggestion.ai_suggested_category);
                  setEditDept(suggestion.ai_suggested_department);
                  setEditVisible(true);
                }}
                style={{ flex: 1 }}
              />
            </View>
          </View>
        ) : null}

        {confirmed && incident ? (
          <View style={[styles.waitCard, { borderColor: colors.success }]} testID="ai-confirmed-note">
            <CheckCircle2 size={20} color={colors.success} strokeWidth={2.2} />
            <Text style={[styles.waitText, { color: colors.success }]}>
              {t("incident.aiRouted", { dept: deptName(incident.department_code) })}
            </Text>
          </View>
        ) : null}
      </ScrollView>

      <View style={styles.footer}>
        <BigButton
          testID="success-home-button"
          label={t("common.home")}
          icon={Home}
          height={64}
          onPress={() => router.replace("/")}
        />
      </View>

      <Modal
        visible={editVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setEditVisible(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalSheet} testID="ai-edit-modal">
            <ScrollView style={styles.modalScroll} nestedScrollEnabled>
              <Text style={styles.modalTitle}>{t("incident.chooseCategory")}</Text>
              <View style={styles.catGrid}>
                {INCIDENT_CATEGORIES.map((c) => {
                  const Icon = c.icon;
                  const active = editCat === c.code;
                  return (
                    <Pressable
                      key={c.code}
                      testID={`edit-cat-${c.code}`}
                      onPress={() => setEditCat(c.code)}
                      style={[styles.catChip, active && styles.catChipActive]}
                    >
                      <Icon size={22} color={active ? colors.primary : c.tint} strokeWidth={2.2} />
                      <Text style={[styles.catChipText, active && { color: colors.primary }]}>
                        {t(c.tKey)}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={styles.modalTitle}>{t("incident.aboutDept")}</Text>
              {(departments.data ?? []).map((item) => {
                const Icon = departmentIcon(item.code);
                const active = item.code === editDept;
                return (
                  <Pressable
                    key={item.code}
                    testID={`edit-dept-${item.code}`}
                    onPress={() => setEditDept(item.code)}
                    style={[styles.deptRow, active && styles.deptRowActive]}
                  >
                    <Icon size={22} color={active ? colors.primary : colors.muted} strokeWidth={2.2} />
                    <Text style={[styles.deptRowText, active && { color: colors.primary }]}>
                      {tri(item as unknown as Record<string, unknown>, "name")}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
            <View style={styles.aiActions}>
              <BigButton
                testID="ai-edit-cancel-button"
                label={t("common.cancel")}
                variant="muted"
                disabled={confirming}
                onPress={() => setEditVisible(false)}
                style={{ flex: 1 }}
              />
              <BigButton
                testID="ai-edit-confirm-button"
                label={t("common.confirm")}
                variant="success"
                loading={confirming}
                disabled={!editCat || !editDept}
                onPress={() =>
                  void confirm({ category: editCat ?? undefined, department_code: editDept ?? undefined })
                }
                style={{ flex: 1 }}
              />
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.lg },
  center: { alignItems: "center", gap: spacing.sm, paddingTop: spacing.xl },
  circle: {
    width: 116,
    height: 116,
    borderRadius: 58,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.md,
  },
  title: { fontFamily: fonts.bold, fontSize: type.xxl, color: colors.text, textAlign: "center" },
  body: { fontFamily: fonts.regular, fontSize: type.lg, color: colors.muted, textAlign: "center" },
  rid: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.primary,
    marginTop: spacing.sm,
  },
  returning: {
    fontFamily: fonts.regular,
    fontSize: type.sm,
    color: colors.muted,
    marginTop: spacing.lg,
  },
  waitCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginTop: spacing.md,
  },
  waitText: { fontFamily: fonts.medium, fontSize: type.base, color: colors.muted, flex: 1 },
  aiCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.primary,
    padding: spacing.lg,
    gap: spacing.md,
    marginTop: spacing.md,
  },
  aiHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  aiTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, flex: 1 },
  aiConfidence: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.muted },
  aiRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  aiIcon: {
    width: 52,
    height: 52,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  aiCat: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  aiDept: { fontFamily: fonts.medium, fontSize: type.base, color: colors.muted },
  aiActions: { flexDirection: "row", gap: spacing.md },
  footer: { padding: sizes.screenPadding, paddingTop: 0 },
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
    maxHeight: "75%",
    gap: spacing.md,
  },
  modalScroll: { flexGrow: 0 },
  modalTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, marginTop: spacing.xs },
  catGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  catChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    minHeight: 44,
  },
  catChipActive: { borderColor: colors.primary, backgroundColor: colors.brandTertiary },
  catChipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  deptRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
  },
  deptRowActive: { backgroundColor: colors.brandTertiary },
  deptRowText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
});
