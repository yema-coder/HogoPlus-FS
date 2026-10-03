import React, { useEffect, useState } from "react";
import {
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useTranslation } from "react-i18next";

import { adminDesignations, listDepartments } from "@/src/api/endpoints";
import type { DepartmentItem } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { tri } from "@/src/i18n";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

const SHIFTS = ["GEN", "A", "B", "C"];
const PHONE_REGEX = /^\+91[6-9]\d{9}$/;
// Core job titles always offered in the Role picker, even before the server list loads.
const CORE_TITLES = [
  "Fieldman", "Slipboy", "Agriculture Overseer", "Agriculture Officer",
  "Cane Supply Officer", "Clerk", "Sr. Clerk", "Peon", "Helper", "Watchman",
  "Driver", "Manager", "Supervisor",
];
// Derive the login/permission role from the chosen job title (only used when
// CREATING). Everyone defaults to Worker; an explicit Manager/Clerk title lifts it.
const roleFromTitle = (title: string): string => {
  const d = title.trim().toLowerCase();
  if (/\bmanager\b/.test(d)) return "Manager";
  if (/\bclerk\b/.test(d)) return "Clerk";
  return "Worker";
};
export interface EmployeeFormValues {
  full_name: string;
  phone: string;
  department_code: string;
  role_code: string;
  shift_code: string;
  emp_id: string;
  designation: string;
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
  // edit mode defaults to KEEP: never overwrite today's shift unless explicitly changed
  const shifts = mode === "edit" ? ["KEEP", ...SHIFTS] : SHIFTS;

  const [departments, setDepartments] = useState<DepartmentItem[]>([]);
  const [desigList, setDesigList] = useState<string[]>([]);
  const [values, setValues] = useState<EmployeeFormValues>({
    full_name: initial.full_name ?? "",
    phone: initial.phone ?? "+91",
    department_code: initial.department_code ?? "",
    role_code: initial.role_code ?? "Worker",
    shift_code: initial.shift_code ?? (mode === "edit" ? "KEEP" : "GEN"),
    emp_id: initial.emp_id ?? "",
    designation: initial.designation ?? "",
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
    void adminDesignations()
      .then((r) => setDesigList(r.designations))
      .catch(() => undefined);
  }, []);

  const set = <K extends keyof EmployeeFormValues>(key: K, val: EmployeeFormValues[K]) =>
    setValues((v) => ({ ...v, [key]: val }));

  const phoneOk = PHONE_REGEX.test(values.phone.trim());
  // Merge core titles first so Fieldman/Slipboy etc. are always offered.
  const titleOptions = Array.from(new Set([...CORE_TITLES, ...desigList]));
  // job-title type-ahead: top suggestions, filtered as the user types
  const desigSuggestions = (
    values.designation.trim()
      ? titleOptions.filter(
          (d) =>
            d.toLowerCase().includes(values.designation.trim().toLowerCase()) &&
            d !== values.designation,
        )
      : titleOptions
  ).slice(0, 8);
  const canSubmit =
    values.full_name.trim().length >= 2 &&
    phoneOk &&
    !!values.department_code &&
    !!values.role_code &&
    (mode === "edit" || values.emp_id.trim().length >= 1);

  return (
    <KeyboardAwareScrollView
      style={{ flex: 1 }}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
    >
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
        <TextInput
          testID="emp-desig-input"
          style={styles.input}
          value={values.designation}
          onChangeText={(v) => set("designation", v)}
          placeholder={t("emp.wiz.desigHint")}
          placeholderTextColor={colors.muted}
        />
        {desigSuggestions.length > 0 ? (
          <View style={styles.chipsWrap}>
            {desigSuggestions.map((d) => (
              <Pressable
                key={d}
                testID={`emp-desig-${d}`}
                onPress={() => set("designation", d)}
                style={[styles.chip, values.designation === d && styles.chipActive]}
              >
                <Text style={[styles.chipText, values.designation === d && styles.chipTextActive]}>
                  {d}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}

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
          onPress={() =>
            onSubmit({
              ...values,
              role_code: mode === "edit" ? values.role_code : roleFromTitle(values.designation),
              phone: values.phone.trim(),
            })
          }
        />
    </KeyboardAwareScrollView>
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
