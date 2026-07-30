import { Building2, UserRound } from "lucide-react-native";
import React, { useEffect, useMemo, useState } from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useTranslation } from "react-i18next";

import { ApiError, localizedDetail } from "@/src/api/client";
import { escalateIncident, escalationTargets, listDepartments } from "@/src/api/endpoints";
import type { DepartmentItem, EscalationTarget } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { showToast } from "@/src/components/Toast";
import { tri } from "@/src/i18n";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

interface Props {
  incidentId: string;
  visible: boolean;
  onClose: () => void;
  onDone: () => void;
}

/** Prompt 17 Part E: manual escalation — pick a department (its manager) or a
 * specific Manager/CGM/MD, with a mandatory reason. */
export function EscalateModal({ incidentId, visible, onClose, onDone }: Props) {
  const { t, i18n } = useTranslation();
  const [mode, setMode] = useState<"department" | "employee">("department");
  const [departments, setDepartments] = useState<DepartmentItem[]>([]);
  const [targets, setTargets] = useState<EscalationTarget[]>([]);
  const [deptCode, setDeptCode] = useState<string | null>(null);
  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  // Prompt 21 Bug 4: toasts fired inside a native Modal render BEHIND it on
  // Android — errors must be shown INSIDE the sheet.
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) return;
    setError(null);
    void listDepartments()
      .then(setDepartments)
      .catch(() => setError(t("errors.network")));
    void escalationTargets()
      .then(setTargets)
      .catch(() => setError(t("errors.network")));
  }, [visible, t]);

  const filteredTargets = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return targets;
    return targets.filter(
      (e) => e.full_name.toLowerCase().includes(q) || e.emp_id.toLowerCase().includes(q),
    );
  }, [targets, search]);

  const canSubmit =
    reason.trim().length >= 3 &&
    ((mode === "department" && !!deptCode) || (mode === "employee" && !!employeeId));

  const submit = async () => {
    if (!canSubmit || sending) return;
    setSending(true);
    setError(null);
    try {
      await escalateIncident(incidentId, {
        mode,
        department_code: mode === "department" ? deptCode ?? undefined : undefined,
        employee_id: mode === "employee" ? employeeId ?? undefined : undefined,
        reason: reason.trim(),
      });
      showToast(t("escalate.done"), "success");
      setReason("");
      setDeptCode(null);
      setEmployeeId(null);
      onDone();
    } catch (e) {
      // shown INSIDE the sheet — a toast would be hidden behind the native modal
      const localized = localizedDetail(e, i18n.language || "mr");
      if (localized) setError(localized);
      else if (e instanceof ApiError && e.status === 0) setError(t("errors.network"));
      else if (e instanceof ApiError && e.status === 409) setError(t("errors.generic"));
      else setError(t("errors.server"));
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView behavior="padding" style={styles.backdrop}>
        <View style={styles.sheet} testID="escalate-modal">
          <Text style={styles.title}>{t("escalate.title")}</Text>

          <View style={styles.modeRow}>
            {(
              [
                { key: "department" as const, label: t("escalate.toDept"), Icon: Building2 },
                { key: "employee" as const, label: t("escalate.toPerson"), Icon: UserRound },
              ]
            ).map(({ key, label, Icon }) => (
              <Pressable
                key={key}
                testID={`escalate-mode-${key}`}
                onPress={() => setMode(key)}
                style={[styles.modeChip, mode === key && styles.modeChipActive]}
              >
                <Icon size={18} color={mode === key ? colors.onPrimary : colors.primary} strokeWidth={2.2} />
                <Text style={[styles.modeChipText, mode === key && styles.modeChipTextActive]}>
                  {label}
                </Text>
              </Pressable>
            ))}
          </View>

          {mode === "employee" ? (
            <TextInput
              testID="escalate-person-search"
              style={styles.search}
              value={search}
              onChangeText={setSearch}
              placeholder={t("escalate.searchPerson")}
              placeholderTextColor={colors.muted}
            />
          ) : null}

          <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
            {mode === "department"
              ? departments.map((d) => (
                  <Pressable
                    key={d.code}
                    testID={`escalate-dept-${d.code}`}
                    onPress={() => setDeptCode(d.code)}
                    style={[styles.item, deptCode === d.code && styles.itemActive]}
                  >
                    <Text style={[styles.itemText, deptCode === d.code && styles.itemTextActive]}>
                      {tri(d as unknown as Record<string, unknown>, "name")}
                    </Text>
                  </Pressable>
                ))
              : filteredTargets.map((e) => (
                  <Pressable
                    key={e.id}
                    testID={`escalate-person-${e.emp_id}`}
                    onPress={() => setEmployeeId(e.id)}
                    style={[styles.item, employeeId === e.id && styles.itemActive]}
                  >
                    <Text style={[styles.itemText, employeeId === e.id && styles.itemTextActive]}>
                      {e.full_name}
                    </Text>
                    <Text style={styles.itemSub}>
                      {e.emp_id} · {e.role_code} · {e.department_code}
                    </Text>
                  </Pressable>
                ))}
          </ScrollView>

          <TextInput
            testID="escalate-reason-input"
            style={styles.reason}
            value={reason}
            onChangeText={setReason}
            placeholder={t("escalate.reasonPlaceholder")}
            placeholderTextColor={colors.muted}
            multiline
          />

          {error ? (
            <Text style={styles.errorText} testID="escalate-error">
              {error}
            </Text>
          ) : null}

          <View style={styles.actions}>
            <BigButton
              testID="escalate-submit-button"
              label={t("escalate.submit")}
              variant="accent"
              loading={sending}
              disabled={!canSubmit}
              onPress={() => void submit()}
            />
            <BigButton
              testID="escalate-cancel-button"
              label={t("common.cancel")}
              variant="outline"
              onPress={onClose}
            />
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    padding: spacing.xl,
    maxHeight: "88%",
    gap: spacing.md,
  },
  title: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  modeRow: { flexDirection: "row", gap: spacing.sm },
  modeChip: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    paddingVertical: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    borderColor: colors.primary,
    backgroundColor: colors.surface,
  },
  modeChipActive: { backgroundColor: colors.primary },
  modeChipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.primary },
  modeChipTextActive: { color: colors.onPrimary },
  search: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    backgroundColor: colors.surface,
  },
  list: { maxHeight: 240 },
  item: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    marginBottom: spacing.xs,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  itemActive: { borderColor: colors.primary, backgroundColor: "#E8F1F5" },
  itemText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  itemTextActive: { color: colors.primary },
  itemSub: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, marginTop: 2 },
  reason: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    minHeight: 64,
    textAlignVertical: "top",
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    backgroundColor: colors.surface,
  },
  actions: { gap: spacing.sm },
  errorText: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.danger,
    backgroundColor: `${colors.danger}12`,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
});
