import { useRouter } from "expo-router";
import React, { useEffect, useState } from "react";
import { StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import { directAddEmployee, empIdSuggest } from "@/src/api/endpoints";
import { EmployeeForm, type EmployeeFormValues } from "@/src/components/EmployeeForm";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { colors } from "@/src/theme/tokens";

/** Prompt 17 Part B: direct-add employee (no OTP self-registration round-trip).
 * Created ACTIVE immediately — they can log in with their phone right away. */
export default function NewEmployeeScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const [suggestedId, setSuggestedId] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void empIdSuggest()
      .then((r) => setSuggestedId(r.suggested_emp_id))
      .catch(() => undefined);
  }, []);

  const submit = async (values: EmployeeFormValues) => {
    setSubmitting(true);
    try {
      await directAddEmployee({
        full_name: values.full_name.trim(),
        phone: values.phone,
        department_code: values.department_code,
        role_code: values.role_code,
        shift_code: values.shift_code,
        emp_id: values.emp_id.trim(),
      });
      showToast(t("emp.created"), "success");
      router.back();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const detail = typeof e.detail === "string" ? e.detail : "";
        showToast(detail.includes("phone") ? t("emp.phoneTaken") : t("emp.idTaken"), "error");
      } else if (e instanceof ApiError && e.status === 403) {
        showToast(t("emp.notAllowed"), "error");
      } else if (e instanceof ApiError && e.status === 0) {
        showToast(t("errors.network"), "error");
      } else {
        showToast(t("errors.server"), "error");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="new-employee-screen">
      <ScreenHeader title={t("emp.add")} />
      <EmployeeForm
        mode="create"
        initial={{ emp_id: suggestedId }}
        submitLabel={t("emp.create")}
        submitting={submitting}
        onSubmit={(v) => void submit(v)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
});
