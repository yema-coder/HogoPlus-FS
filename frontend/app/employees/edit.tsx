import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useMemo, useState } from "react";
import { StyleSheet, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { patchEmployee } from "@/src/api/endpoints";
import type { EmployeeProfile } from "@/src/api/types";
import { EmployeeForm, type EmployeeFormValues } from "@/src/components/EmployeeForm";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { colors, fonts, sizes, type } from "@/src/theme/tokens";

/** Prompt 17 Part B: edit an employee's access with guardrails — only changed
 * fields are PATCHed; the backend blocks Time Office from touching Manager+
 * accounts or granting Manager+ roles. Role changes propagate WITHOUT re-login
 * (the target's app refreshes its profile on next foreground). */
export default function EditEmployeeScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const { emp } = useLocalSearchParams<{ emp: string }>();
  const [submitting, setSubmitting] = useState(false);

  const employee = useMemo<EmployeeProfile | null>(() => {
    try {
      return emp ? (JSON.parse(emp) as EmployeeProfile) : null;
    } catch {
      return null;
    }
  }, [emp]);

  const submit = async (values: EmployeeFormValues) => {
    if (!employee) return;
    const body: Record<string, unknown> = {};
    if (values.full_name.trim() !== employee.full_name) body.full_name = values.full_name.trim();
    if (values.phone !== (employee.phone ?? "+91")) body.phone = values.phone;
    if (values.department_code !== employee.department_code) body.department_code = values.department_code;
    if (values.role_code !== employee.role_code) body.role_code = values.role_code;
    if (values.is_active !== employee.is_active) body.is_active = values.is_active;
    if (values.shift_code && values.shift_code !== "KEEP") body.shift_code = values.shift_code;
    if (Object.keys(body).length === 0) {
      router.back();
      return;
    }
    setSubmitting(true);
    try {
      await patchEmployee(employee.id, body);
      showToast(t("emp.saved"), "success");
      router.back();
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) showToast(t("emp.notAllowed"), "error");
      else if (e instanceof ApiError && e.status === 409) showToast(t("emp.phoneTaken"), "error");
      else if (e instanceof ApiError && e.status === 0) showToast(t("errors.network"), "error");
      else showToast(t("errors.server"), "error");
    } finally {
      setSubmitting(false);
    }
  };

  if (!employee) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]}>
        <ScreenHeader title={t("emp.edit")} />
        <Text style={styles.missing}>{t("errors.generic")}</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="edit-employee-screen">
      <ScreenHeader title={`${t("emp.edit")} · ${employee.emp_id}`} />
      <EmployeeForm
        mode="edit"
        initial={{
          full_name: employee.full_name,
          phone: employee.phone ?? "+91",
          department_code: employee.department_code,
          role_code: employee.role_code,
          is_active: employee.is_active,
        }}
        submitLabel={t("emp.save")}
        submitting={submitting}
        onSubmit={(v) => void submit(v)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  missing: {
    textAlign: "center",
    marginTop: sizes.screenPadding,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
  },
});
