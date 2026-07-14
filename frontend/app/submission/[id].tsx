import dayjs from "dayjs";
import { useLocalSearchParams } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import {
  approveSubmission,
  listForms,
  rejectSubmission,
  submissionDetail,
} from "@/src/api/endpoints";
import type { FormDefinitionItem, SubmissionItem } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { StatusChip } from "@/src/components/StatusChip";
import { ReadOnlyField } from "@/src/forms/ReadOnlyField";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useApprovalsStore } from "@/src/stores/approvalsStore";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatDateTime } from "@/src/utils/format";

export default function SubmissionDetailScreen() {
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const profile = useAuthStore((s) => s.profile);
  const rank = profile?.role?.rank ?? 6;
  const adjust = useApprovalsStore((s) => s.adjust);

  const [sub, setSub] = useState<SubmissionItem | null>(null);
  const [failed, setFailed] = useState(false);
  const [acting, setActing] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState("");

  const defs = useCachedFetch<FormDefinitionItem[]>(
    `forms-${sub?.department_code ?? "none"}`,
    () => listForms(sub && rank <= 3 ? sub.department_code : undefined),
  );

  const load = useCallback(async () => {
    if (!id) return;
    setFailed(false);
    try {
      setSub(await submissionDetail(id));
    } catch {
      setFailed(true);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (sub) void defs.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub?.department_code]);

  const definition = sub
    ? (defs.data?.find((d) => d.id === sub.form_definition_id) ??
      defs.data?.find((d) => d.code === sub.form_code) ??
      null)
    : null;

  const pending = sub && (sub.status === "submitted" || sub.status === "escalated");
  const canAct = pending && rank <= 3 && sub?.submitted_by !== profile?.id;

  const doApprove = async () => {
    if (!sub || acting) return;
    setActing(true);
    adjust("forms", -1);
    try {
      await approveSubmission(sub.id);
      showToast(t("approvals.actionDone"), "success");
      await load();
    } catch (e) {
      adjust("forms", 1);
      showToast(e instanceof ApiError && e.status === 0 ? t("errors.network") : t("errors.server"), "error");
    } finally {
      setActing(false);
    }
  };

  const doReject = async () => {
    if (!sub || acting || reason.trim().length === 0) return;
    setActing(true);
    adjust("forms", -1);
    try {
      await rejectSubmission(sub.id, reason.trim());
      setRejectOpen(false);
      setReason("");
      showToast(t("approvals.actionDone"), "success");
      await load();
    } catch (e) {
      adjust("forms", 1);
      showToast(e instanceof ApiError && e.status === 0 ? t("errors.network") : t("errors.server"), "error");
    } finally {
      setActing(false);
    }
  };

  const title = definition
    ? tri(definition as unknown as Record<string, unknown>, "title")
    : ((sub && tri(sub as unknown as Record<string, unknown>, "form_title")) || t("forms.title"));

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="submission-detail-screen">
      <ScreenHeader title={title} />
      {failed ? (
        <ErrorRetry onRetry={() => void load()} />
      ) : !sub ? (
        <View style={styles.loading}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={styles.headRow}>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.byLine}>
                {t("forms.submittedBy")}: {sub.submitted_by_name ?? "—"}
                {sub.submitted_by_emp_id ? ` · ${sub.submitted_by_emp_id}` : ""}
              </Text>
              <Text style={styles.meta}>{formatDateTime(sub.created_at)}</Text>
            </View>
            <StatusChip status={sub.status} />
          </View>

          {sub.status === "rejected" && sub.rejection_reason ? (
            <View style={styles.rejectCard} testID="rejection-reason-card">
              <Text style={styles.rejectLabel}>{t("forms.rejectionReason")}</Text>
              <Text style={styles.rejectText}>{sub.rejection_reason}</Text>
            </View>
          ) : null}

          <View style={styles.card}>
            {definition ? (
              definition.schema_json.fields.map((f) => (
                <ReadOnlyField key={f.key} field={f} value={sub.data_json[f.key]} />
              ))
            ) : (
              Object.entries(sub.data_json).map(([k, v]) => (
                <View key={k} style={styles.rawRow}>
                  <Text style={styles.rawKey}>{k}</Text>
                  <Text style={styles.rawVal}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</Text>
                </View>
              ))
            )}
          </View>

          {sub.approved_at ? (
            <Text style={styles.meta}>
              {t(`status.${sub.status}`)} · {dayjs(sub.approved_at).format("DD/MM/YYYY HH:mm")}
            </Text>
          ) : null}

          {canAct ? (
            <View style={styles.actions}>
              <BigButton
                testID="reject-submission-button"
                label={t("approvals.reject")}
                variant="danger"
                disabled={acting}
                onPress={() => setRejectOpen(true)}
                style={{ flex: 1 }}
              />
              <BigButton
                testID="approve-submission-button"
                label={t("approvals.approve")}
                variant="success"
                loading={acting}
                height={64}
                onPress={() => void doApprove()}
                style={{ flex: 2 }}
              />
            </View>
          ) : null}
        </ScrollView>
      )}

      <Modal visible={rejectOpen} transparent animationType="fade" onRequestClose={() => setRejectOpen(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard} testID="reject-reason-modal">
            <Text style={styles.modalTitle}>{t("approvals.rejectReason")}</Text>
            <TextInput
              testID="reject-reason-input"
              style={styles.reasonInput}
              value={reason}
              onChangeText={setReason}
              placeholder={t("forms.rejectionReason")}
              placeholderTextColor={colors.muted}
              multiline
              maxLength={300}
            />
            <View style={styles.modalActions}>
              <BigButton
                testID="reject-cancel-button"
                label={t("common.cancel")}
                variant="muted"
                onPress={() => setRejectOpen(false)}
                style={{ flex: 1 }}
              />
              <BigButton
                testID="reject-confirm-button"
                label={t("approvals.reject")}
                variant="danger"
                loading={acting}
                disabled={reason.trim().length === 0}
                onPress={() => void doReject()}
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
  loading: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.xxl },
  headRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  byLine: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  meta: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  rejectCard: {
    backgroundColor: "#FDECEC",
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.danger,
    padding: spacing.lg,
    gap: 4,
  },
  rejectLabel: { fontFamily: fonts.bold, fontSize: type.sm, color: colors.danger },
  rejectText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  rawRow: { paddingVertical: spacing.sm, gap: 2 },
  rawKey: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  rawVal: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  actions: { flexDirection: "row", gap: spacing.md, marginTop: spacing.sm, alignItems: "center" },
  modalBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    padding: sizes.screenPadding,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.md,
  },
  modalTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  reasonInput: {
    minHeight: 72,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    textAlignVertical: "top",
  },
  modalActions: { flexDirection: "row", gap: spacing.md },
});
