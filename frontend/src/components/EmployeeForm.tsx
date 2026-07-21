import React, { useEffect, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { useTranslation } from "react-i18next";

import { listDepartments } from "@/src/api/endpoints";
import type { DepartmentItem } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { tri } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

const SHIFTS = ["GEN", "A", "B", "C"];
const PHONE_REGEX = /^\+91[6-9]\d{9}$/;
export interface EmployeeFormValues {
  full_name: string;
  phone: string;
  department_code: string;
  role_code: string;
  shift_code: string;
  emp_id: string;
  is_active: boolean;
}

interface Props {
  mode: "create" | "edit";
  initial: Partial<EmployeeFormValues>;
  submitLabel: string;
  submitting: boolean;
  onSubmit: (values: EmployeeFormValues) => void;
}

/** Shared direct-add / edit employee form (Prompt 17 Part B). The Manager role
 * chip is only offered to CGM/MD — Time Office is limited to Worker/Staff/Clerk
 * (the backend enforces this regardless). */
export function EmployeeForm({ mode, initial, submitLabel, submitting, onSubmit }: Props) {
  const { t } = useTranslation();
  const rank = useAuthStore((s) => s.profile?.role?.rank ?? 6);
  const roles = rank <= 2 ? ["Worker", "Staff", "Clerk", "Manager"] : ["Worker", "Staff", "Clerk"];
  // edit mode defaults to KEEP: never overwrite today's shift unless explicitly changed
  const shifts = mode === "edit" ? ["KEEP", ...SHIFTS] : SHIFTS;

  const [departments, setDepartments] = useState<DepartmentItem[]>([]);
  const [values, setValues] = useState<EmployeeFormValues>({
    full_name: initial.full_name ?? "",
    phone: initial.phone ?? "+91",
    department_code: initial.department_code ?? "",
    role_code: initial.role_code ?? "Worker",
    shift_code: initial.shift_code ?? (mode === "edit" ? "KEEP" : "GEN"),
    emp_id: initial.emp_id ?? "",
    is_active: initial.is_active ?? true,
  });

  // edit-mode async prefill (emp_id suggestion arrives after mount)
  useEffect(() => {
    if (mode === "create" && initial.emp_id && !values.emp_id) {
      setValues((v) => ({ ...v, emp_id: initial.emp_id ?? "" }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial.emp_id]);

  useEffect(() => {
    void listDepartments().then(setDepartments).catch(() => undefined);
  }, []);

  const set = <K extends keyof EmployeeFormValues>(key: K, val: EmployeeFormValues[K]) =>
    setValues((v) => ({ ...v, [key]: val }));

  const phoneOk = PHONE_REGEX.test(values.phone.trim());
  const canSubmit =
    values.full_name.trim().length >= 2 &&
    phoneOk &&
    !!values.department_code &&
    !!values.role_code &&
    (mode === "edit" || values.emp_id.trim().length >= 1);

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.label}>{t("emp.name")}</Text>
        <TextInput
          testID="emp-name-input"
          style={styles.input}
          value={values.full_name}
          onChangeText={(v) => set("full_name", v)}
          placeholder={t("emp.name")}
          placeholderTextColor={colors.muted}
        />

        <Text style={styles.label}>{t("emp.phone")}</Text>
        <TextInput
          testID="emp-phone-input"
          style={styles.input}
          value={values.phone}
          onChangeText={(v) => {
            let clean = v.replace(/[^\d+]/g, "");
            if (!clean.startsWith("+91")) clean = `+91${clean.replace(/^\+?9?1?/, "")}`;
            set("phone", clean);
          }}
          placeholder="+91XXXXXXXXXX"
          placeholderTextColor={colors.muted}
          keyboardType="phone-pad"
          maxLength={13}
        />
        {values.phone.length > 3 && !phoneOk ? (
          <Text style={styles.fieldError}>{t("emp.phoneInvalid")}</Text>
        ) : null}

        {mode === "create" ? (
          <>
            <Text style={styles.label}>{t("emp.empId")}</Text>
            <TextInput
              testID="emp-id-input"
              style={styles.input}
              value={values.emp_id}
              onChangeText={(v) => set("emp_id", v)}
              placeholder="0000"
              placeholderTextColor={colors.muted}
              autoCapitalize="characters"
              maxLength={20}
            />
          </>
        ) : null}

        <Text style={styles.label}>{t("emp.dept")}</Text>
        <View style={styles.chipsWrap}>
          {departments.map((d) => (
            <Pressable
              key={d.code}
              testID={`emp-dept-${d.code}`}
              onPress={() => set("department_code", d.code)}
              style={[styles.chip, values.department_code === d.code && styles.chipActive]}
            >
              <Text
                style={[styles.chipText, values.department_code === d.code && styles.chipTextActive]}
              >
                {tri(d as unknown as Record<string, unknown>, "name")}
              </Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.label}>{t("emp.role")}</Text>
        <View style={styles.chipsWrap}>
          {roles.map((r) => (
            <Pressable
              key={r}
              testID={`emp-role-${r}`}
              onPress={() => set("role_code", r)}
              style={[styles.chip, values.role_code === r && styles.chipActive]}
            >
              <Text style={[styles.chipText, values.role_code === r && styles.chipTextActive]}>
                {r}
              </Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.label}>{t("emp.shift")}</Text>
        <View style={styles.chipsWrap}>
          {shifts.map((s) => (
            <Pressable
              key={s}
              testID={`emp-shift-${s}`}
              onPress={() => set("shift_code", s)}
              style={[styles.chip, values.shift_code === s && styles.chipActive]}
            >
              <Text style={[styles.chipText, values.shift_code === s && styles.chipTextActive]}>
                {s === "KEEP" ? t("emp.keepShift") : s}
              </Text>
            </Pressable>
          ))}
        </View>

        {mode === "edit" ? (
          <View style={styles.activeRow}>
            <Text style={styles.activeLabel}>{t("emp.active")}</Text>
            <Switch
              testID="emp-active-switch"
              value={values.is_active}
              onValueChange={(v) => set("is_active", v)}
              trackColor={{ true: colors.primary, false: colors.border }}
            />
          </View>
        ) : null}

        <BigButton
          testID="emp-submit-button"
          label={submitLabel}
          loading={submitting}
          disabled={!canSubmit}
          onPress={() => onSubmit({ ...values, phone: values.phone.trim() })}
        />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  content: { padding: sizes.screenPadding, gap: spacing.sm, paddingBottom: spacing.xxl },
  label: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.muted,
    marginTop: spacing.md,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
    backgroundColor: colors.surface,
    minHeight: 52,
  },
  fieldError: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.danger },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    minHeight: 44,
    justifyContent: "center",
  },
  chipActive: { borderColor: colors.primary, backgroundColor: colors.primary },
  chipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  chipTextActive: { color: colors.onPrimary },
  activeRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  activeLabel: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
});
