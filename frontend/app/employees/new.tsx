import { useRouter } from "expo-router";
import { Check, ChevronRight } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/src/api/client";
import {
  adminDesignations,
  directAddEmployee,
  empIdSuggest,
  employeeAvailability,
  listDepartments,
} from "@/src/api/endpoints";
import type { DepartmentItem } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { tri } from "@/src/i18n";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

const EMP_ID_RE = /^[A-Za-z0-9]{1,20}$/;
// Core job titles always offered in the Role picker, even before the server list loads.
const CORE_TITLES = [
  "Fieldman", "Slipboy", "Agriculture Overseer", "Agriculture Officer",
  "Cane Supply Officer", "Clerk", "Sr. Clerk", "Peon", "Helper", "Watchman",
  "Driver", "Manager", "Supervisor",
];
// Derive the login/permission role from the chosen job title. Everyone defaults
// to Worker; an explicit Manager/Clerk title lifts the access level.
const roleFromTitle = (title: string): string => {
  const d = title.trim().toLowerCase();
  if (/\bmanager\b/.test(d)) return "Manager";
  if (/\bclerk\b/.test(d)) return "Clerk";
  return "Worker";
};
const normPhone = (raw: string): string | null => {
  const d = raw.replace(/\D/g, "");
  const ten =
    d.length === 12 && d.startsWith("91")
      ? d.slice(2)
      : d.length === 11 && d.startsWith("0")
        ? d.slice(1)
        : d.length === 10
          ? d
          : null;
  return ten && /^[6-9]/.test(ten) ? `+91${ten}` : null;
};

const TOTAL_STEPS = 5;

/** v1.0.24 step-by-step add-employee wizard — ONE field per screen. The old
 * all-at-once form produced half-empty records in the field (people typed just
 * the number and skipped the rest). Required steps are unskippable; uniqueness
 * is validated per-step and the server re-validates everything on submit. */
export default function NewEmployeeWizard() {
  const router = useRouter();
  const { t } = useTranslation();
  const [step, setStep] = useState(0); // 0 name, 1 emp_id, 2 dept+role, 3 phone, 4 review
  const [name, setName] = useState("");
  const [empId, setEmpId] = useState("");
  const [dept, setDept] = useState("");
  const [desig, setDesig] = useState("");
  const [desigList, setDesigList] = useState<string[]>([]);
  const [phone, setPhone] = useState("");
  const [depts, setDepts] = useState<DepartmentItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    void empIdSuggest()
      .then((r) => setEmpId((v) => v || r.suggested_emp_id))
      .catch(() => undefined);
    void listDepartments()
      .then(setDepts)
      .catch(() => undefined);
    void adminDesignations()
      .then((r) => setDesigList(r.designations))
      .catch(() => undefined);
  }, []);

  const phoneNorm = normPhone(phone);
  // Merge the server list with core titles so the Role picker is never empty.
  const titleOptions = Array.from(new Set([...CORE_TITLES, ...desigList]));
  // job-title type-ahead: top suggestions, filtered as the user types
  const desigSuggestions = (
    desig.trim()
      ? titleOptions.filter((d) => d.toLowerCase().includes(desig.trim().toLowerCase()) && d !== desig)
      : titleOptions
  ).slice(0, 8);
  const stepValid = [
    name.trim().length >= 2,
    EMP_ID_RE.test(empId.trim()),
    dept !== "" && desig.trim() !== "",
    phoneNorm !== null,
    true,
  ][step];

  const back = () => {
    if (step === 0) {
      if (router.canGoBack()) router.back();
      else router.replace("/(tabs)/home");
      return;
    }
    setErr("");
    setStep((s) => s - 1);
  };

  const next = async () => {
    setErr("");
    if (step === 1 || step === 3) {
      setBusy(true);
      try {
        const r = await employeeAvailability(
          step === 1 ? { emp_id: empId.trim() } : { phone: phoneNorm! },
        );
        const takenBy = step === 1 ? r.emp_id_taken_by : r.phone_taken_by;
        if (takenBy) {
          setErr(
            step === 1
              ? t("emp.wiz.idTaken", { who: takenBy })
              : t("emp.wiz.phoneTaken", { who: takenBy }),
          );
          return;
        }
      } catch {
        // availability check unreachable (offline) — the server re-validates on submit
      } finally {
        setBusy(false);
      }
    }
    setStep((s) => s + 1);
  };

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      await directAddEmployee({
        full_name: name.trim(),
        phone: phoneNorm!,
        department_code: dept,
        role_code: roleFromTitle(desig),
        emp_id: empId.trim(),
        ...(desig.trim() ? { designation: desig.trim() } : {}),
      });
      showToast(t("emp.created"), "success");
      if (router.canGoBack()) router.back();
      else router.replace("/(tabs)/home");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        const detail = typeof e.detail === "string" ? e.detail : "";
        setErr(detail || t("emp.idTaken"));
        setStep(detail.toLowerCase().includes("phone") ? 3 : 1);
      } else if (e instanceof ApiError && e.status === 403) {
        setErr(t("emp.notAllowed"));
      } else {
        setErr(t("errors.server"));
      }
    } finally {
      setBusy(false);
    }
  };

  const titles = [
    t("emp.wiz.nameTitle"),
    t("emp.wiz.idTitle"),
    t("emp.wiz.deptRoleTitle"),
    t("emp.wiz.phoneTitle"),
    t("emp.wiz.reviewTitle"),
  ];

  const reviewRows: [string, string][] = [
    [t("emp.wiz.nameTitle"), name.trim()],
    [t("emp.wiz.idTitle"), empId.trim()],
    [t("emp.dept"), depts.find((d) => d.code === dept) ? tri(depts.find((d) => d.code === dept) as unknown as Record<string, unknown>, "name") : dept],
    [t("emp.role"), desig.trim() || "—"],
    [t("emp.wiz.phoneTitle"), phoneNorm ?? ""],
  ];

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="new-employee-screen">
      <ScreenHeader title={t("emp.add")} onBack={back} />
      <View style={styles.content}>
        {/* progress */}
        <View style={styles.progressRow} testID="wiz-progress">
          {titles.map((_, i) => (
            <View
              key={i}
              style={[styles.progressSeg, { backgroundColor: i <= step ? colors.primary : colors.border }]}
            />
          ))}
        </View>
        <Text style={styles.stepLabel}>
          {t("emp.wiz.progress", { n: step + 1, total: TOTAL_STEPS })} — {titles[step]}
        </Text>

        <ScrollView
          style={{ flex: 1 }}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingBottom: spacing.xl }}
        >
          {step === 0 && (
            <View>
              <Text style={styles.hint}>{t("emp.wiz.nameHint")}</Text>
              <TextInput
                testID="wiz-name"
                style={styles.bigInput}
                value={name}
                onChangeText={setName}
                autoFocus
                placeholder={t("emp.name")}
                placeholderTextColor={colors.muted}
              />
            </View>
          )}
          {step === 1 && (
            <View>
              <Text style={styles.hint}>{t("emp.wiz.idHint")}</Text>
              <TextInput
                testID="wiz-empid"
                style={styles.bigInput}
                value={empId}
                onChangeText={(v) => setEmpId(v.toUpperCase())}
                autoCapitalize="characters"
                autoCorrect={false}
                placeholder="0000"
                placeholderTextColor={colors.muted}
              />
            </View>
          )}
          {step === 2 && (
            <View style={{ gap: spacing.md }}>
              <Text style={styles.sectionLabel}>{t("emp.dept")}</Text>
              <View style={styles.chipWrap}>
                {depts.map((d) => (
                  <Pressable
                    key={d.code}
                    testID={`wiz-dept-${d.code}`}
                    onPress={() => setDept(d.code)}
                    style={[styles.chip, dept === d.code && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, dept === d.code && styles.chipTextActive]}>
                      {tri(d as unknown as Record<string, unknown>, "name")}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <Text style={styles.sectionLabel}>{t("emp.role")}</Text>
              <TextInput
                testID="wiz-desig"
                style={styles.desigInput}
                value={desig}
                onChangeText={setDesig}
                placeholder={t("emp.wiz.desigHint")}
                placeholderTextColor={colors.muted}
              />
              {desigSuggestions.length > 0 ? (
                <View style={styles.chipWrap}>
                  {desigSuggestions.map((d) => (
                    <Pressable
                      key={d}
                      testID={`wiz-desig-opt-${d}`}
                      onPress={() => setDesig(d)}
                      style={[styles.chip, desig === d && styles.chipActive]}
                    >
                      <Text style={[styles.chipText, desig === d && styles.chipTextActive]}>{d}</Text>
                    </Pressable>
                  ))}
                </View>
              ) : null}
            </View>
          )}
          {step === 3 && (
            <View>
              <Text style={styles.hint}>{t("emp.wiz.phoneHint")}</Text>
              <TextInput
                testID="wiz-phone"
                style={styles.bigInput}
                value={phone}
                onChangeText={setPhone}
                keyboardType="phone-pad"
                autoFocus
                placeholder="+91XXXXXXXXXX"
                placeholderTextColor={colors.muted}
              />
              {phone.length > 0 && phoneNorm === null ? (
                <Text style={styles.fieldError}>{t("emp.phoneInvalid")}</Text>
              ) : null}
            </View>
          )}
          {step === 4 && (
            <View style={styles.reviewCard} testID="wiz-review">
              {reviewRows.map(([k, v]) => (
                <View key={k} style={styles.reviewRow}>
                  <Text style={styles.reviewKey}>{k}</Text>
                  <Text style={styles.reviewVal}>{v}</Text>
                </View>
              ))}
            </View>
          )}

          {err ? (
            <Text style={styles.fieldError} testID="wiz-error">
              {err}
            </Text>
          ) : null}
        </ScrollView>

        {step < 4 ? (
          <BigButton
            testID="wiz-next"
            label={busy ? t("emp.wiz.checking") : t("emp.wiz.next")}
            icon={ChevronRight}
            disabled={!stepValid || busy}
            onPress={() => void next()}
          />
        ) : (
          <BigButton
            testID="wiz-confirm"
            label={t("emp.create")}
            icon={Check}
            disabled={busy}
            onPress={() => void submit()}
          />
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { flex: 1, padding: sizes.screenPadding, gap: spacing.md },
  progressRow: { flexDirection: "row", gap: 6 },
  progressSeg: { flex: 1, height: 6, borderRadius: 3 },
  stepLabel: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.muted },
  hint: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, marginBottom: spacing.sm },
  bigInput: {
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    minHeight: 60,
    fontFamily: fonts.semiBold,
    fontSize: type.xl,
    color: colors.text,
  },
  sectionLabel: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  optionalTag: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  desigInput: {
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    minHeight: 52,
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.text,
  },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    minHeight: sizes.touchTarget,
    justifyContent: "center",
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { borderColor: colors.primary, backgroundColor: "#EAF1FB" },
  chipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  chipTextActive: { color: colors.primary },
  fieldError: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.danger,
    marginTop: spacing.sm,
  },
  reviewCard: {
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    padding: spacing.lg,
    gap: spacing.md,
  },
  reviewRow: { flexDirection: "row", justifyContent: "space-between", gap: spacing.md },
  reviewKey: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted },
  reviewVal: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text, flexShrink: 1, textAlign: "right" },
});
