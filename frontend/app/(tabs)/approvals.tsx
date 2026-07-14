import dayjs from "dayjs";
import { useFocusEffect, useRouter } from "expo-router";
import { ClipboardCheck } from "lucide-react-native";
import React, { useCallback, useState } from "react";
import {
  FlatList,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { ApiError, fileUrl } from "@/src/api/client";
import {
  approveAttendance,
  approveEmployee,
  decideSwap,
  flaggedAttendance,
  listDepartments,
  listIncidents,
  listSubmissions,
  pendingEmployees,
  pendingSwaps,
  rejectEmployee,
} from "@/src/api/endpoints";
import type {
  DepartmentItem,
  EmployeeProfile,
  FlaggedAttendance,
  Incident,
  SubmissionItem,
  SwapRequest,
} from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { EmptyState } from "@/src/components/EmptyState";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { StatusChip } from "@/src/components/StatusChip";
import { categoryDef } from "@/src/constants/categories";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useApprovalsStore, type ApprovalCounts } from "@/src/stores/approvalsStore";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatDateTime, formatTime } from "@/src/utils/format";

type Segment = "forms" | "regs" | "swaps" | "incidents" | "attendance";
type AttFilter = "today" | "yesterday" | "all";

const resolveUri = (v: string) => (v.startsWith("http") ? v : fileUrl(v));

export default function ApprovalsScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const rank = profile?.role?.rank ?? 6;
  const isTop = rank <= 2;
  const showAttendance = isTop || (profile?.department_code === "TIME_OFFICE" && rank === 3);
  const counts = useApprovalsStore((s) => s.counts);
  const refreshCounts = useApprovalsStore((s) => s.refresh);
  const adjust = useApprovalsStore((s) => s.adjust);

  const [segment, setSegment] = useState<Segment>("forms");
  const [deptFilter, setDeptFilter] = useState<string | null>(null);
  const [attFilter, setAttFilter] = useState<AttFilter>("today");

  const [subs, setSubs] = useState<SubmissionItem[]>([]);
  const [regs, setRegs] = useState<EmployeeProfile[]>([]);
  const [swaps, setSwaps] = useState<SwapRequest[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [flagged, setFlagged] = useState<FlaggedAttendance[]>([]);
  const [loading, setLoading] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<{ kind: "reg" | "swap"; id: string } | null>(null);
  const [reason, setReason] = useState("");
  const [acting, setActing] = useState(false);

  const departments = useCachedFetch<DepartmentItem[]>("departments", listDepartments);

  const attDate =
    attFilter === "today"
      ? dayjs().format("YYYY-MM-DD")
      : attFilter === "yesterday"
        ? dayjs().subtract(1, "day").format("YYYY-MM-DD")
        : undefined;

  const loadAll = useCallback(async () => {
    setLoading(true);
    const [sub, esc, reg, swp, incSub, incEsc, att] = await Promise.allSettled([
      listSubmissions({ status: "submitted" }),
      listSubmissions({ status: "escalated" }),
      pendingEmployees(),
      pendingSwaps(),
      listIncidents({ status: "submitted" }),
      listIncidents({ status: "escalated" }),
      showAttendance ? flaggedAttendance(attDate) : Promise.resolve([]),
    ]);
    setSubs([
      ...(sub.status === "fulfilled" ? sub.value.items : []),
      ...(esc.status === "fulfilled" ? esc.value.items : []),
    ]);
    setRegs(reg.status === "fulfilled" ? reg.value : []);
    setSwaps(swp.status === "fulfilled" ? swp.value : []);
    setIncidents([
      ...(incSub.status === "fulfilled" ? incSub.value : []),
      ...(incEsc.status === "fulfilled" ? incEsc.value : []),
    ]);
    setFlagged(att.status === "fulfilled" ? (att.value as FlaggedAttendance[]) : []);
    setLoading(false);
    void refreshCounts(showAttendance);
  }, [attDate, showAttendance, refreshCounts]);

  useFocusEffect(
    useCallback(() => {
      void loadAll();
    }, [loadAll]),
  );

  const byDept = <T extends { department_code?: string | null }>(items: T[]): T[] =>
    isTop && deptFilter ? items.filter((i) => i.department_code === deptFilter) : items;

  // ---------- optimistic actions ----------

  const optimistic = async <T,>(
    key: keyof ApprovalCounts,
    remove: () => T,
    restore: (snapshot: T) => void,
    action: () => Promise<unknown>,
  ) => {
    if (acting) return;
    setActing(true);
    const snapshot = remove();
    adjust(key, -1);
    try {
      await action();
      showToast(t("approvals.actionDone"), "success");
    } catch (e) {
      restore(snapshot);
      adjust(key, 1);
      showToast(e instanceof ApiError && e.status === 0 ? t("errors.network") : t("errors.server"), "error");
    } finally {
      setActing(false);
    }
  };

  const actReg = (emp: EmployeeProfile, approve: boolean, rejectReason?: string) =>
    optimistic(
      "regs",
      () => {
        setRegs((prev) => prev.filter((r) => r.id !== emp.id));
        return regs;
      },
      (snap) => setRegs(snap),
      () => (approve ? approveEmployee(emp.id) : rejectEmployee(emp.id, rejectReason ?? "")),
    );

  const actSwap = (swap: SwapRequest, approve: boolean, rejectReason?: string) =>
    optimistic(
      "swaps",
      () => {
        setSwaps((prev) => prev.filter((s) => s.id !== swap.id));
        return swaps;
      },
      (snap) => setSwaps(snap),
      () => decideSwap(swap.id, approve, rejectReason),
    );

  const actAttendance = (rec: FlaggedAttendance) =>
    optimistic(
      "attendance",
      () => {
        setFlagged((prev) => prev.filter((f) => f.id !== rec.id));
        return flagged;
      },
      (snap) => setFlagged(snap),
      () => approveAttendance(rec.id),
    );

  const confirmReject = async () => {
    if (!rejectTarget || reason.trim().length === 0) return;
    const target = rejectTarget;
    setRejectTarget(null);
    if (target.kind === "reg") {
      const emp = regs.find((r) => r.id === target.id);
      if (emp) await actReg(emp, false, reason.trim());
    } else {
      const swap = swaps.find((s) => s.id === target.id);
      if (swap) await actSwap(swap, false, reason.trim());
    }
    setReason("");
  };

  // ---------- segment data ----------

  const segments: { key: Segment; label: string; count: number }[] = [
    { key: "forms", label: t("approvals.formsTab"), count: counts.forms },
    { key: "regs", label: t("approvals.regsTab"), count: counts.regs },
    { key: "swaps", label: t("approvals.swapsTab"), count: counts.swaps },
    { key: "incidents", label: t("approvals.incidentsTab"), count: counts.incidents },
    ...(showAttendance
      ? [{ key: "attendance" as Segment, label: t("approvals.attendanceTab"), count: counts.attendance }]
      : []),
  ];

  const deptName = (code: string | null | undefined) => {
    const d = departments.data?.find((x) => x.code === code);
    return d ? tri(d as unknown as Record<string, unknown>, "name") : (code ?? "");
  };

  const empty = <EmptyState icon={ClipboardCheck} title={t("approvals.empty")} />;

  const listData: unknown[] =
    segment === "forms"
      ? byDept(subs)
      : segment === "regs"
        ? byDept(regs)
        : segment === "swaps"
          ? byDept(swaps)
          : segment === "incidents"
            ? byDept(incidents)
            : byDept(flagged);

  const renderItem = ({ item }: { item: unknown }) => {
    if (segment === "forms") {
      const s = item as SubmissionItem;
      return (
        <Pressable
          testID={`approval-sub-${s.id}`}
          onPress={() => router.push(`/submission/${s.id}`)}
          style={({ pressed }) => [styles.card, { opacity: pressed ? 0.85 : 1 }]}
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.cardTitle} numberOfLines={1}>
              {tri(s as unknown as Record<string, unknown>, "form_title") || s.form_code}
            </Text>
            <Text style={styles.cardMeta} numberOfLines={1}>
              {s.submitted_by_name ?? ""} · {deptName(s.department_code)}
            </Text>
            <Text style={styles.cardMeta}>{formatDateTime(s.created_at)}</Text>
          </View>
          <StatusChip status={s.status} />
        </Pressable>
      );
    }
    if (segment === "regs") {
      const emp = item as EmployeeProfile;
      return (
        <View style={styles.regCard} testID={`approval-reg-${emp.id}`}>
          <View style={styles.regTop}>
            {emp.selfie_url ? (
              <Image source={{ uri: resolveUri(emp.selfie_url) }} style={styles.regSelfie} />
            ) : (
              <View style={[styles.regSelfie, styles.regSelfieEmpty]}>
                <Text style={styles.regInitial}>{emp.full_name.charAt(0)}</Text>
              </View>
            )}
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.cardTitle}>{emp.full_name}</Text>
              <Text style={styles.cardMeta}>{emp.phone}</Text>
              <Text style={styles.cardMeta}>
                {t("approvals.wantsToJoin", { dept: deptName(emp.department_code) })}
              </Text>
            </View>
          </View>
          <View style={styles.actionRow}>
            <BigButton
              testID={`reg-reject-${emp.id}`}
              label={t("approvals.reject")}
              variant="danger"
              disabled={acting}
              onPress={() => setRejectTarget({ kind: "reg", id: emp.id })}
              style={{ flex: 1 }}
            />
            <BigButton
              testID={`reg-approve-${emp.id}`}
              label={t("approvals.approve")}
              variant="success"
              disabled={acting}
              onPress={() => void actReg(emp, true)}
              style={{ flex: 1 }}
            />
          </View>
        </View>
      );
    }
    if (segment === "swaps") {
      const s = item as SwapRequest;
      return (
        <View style={styles.regCard} testID={`approval-swap-${s.id}`}>
          <Text style={styles.cardTitle}>{dayjs(s.swap_date).format("DD/MM/YYYY")}</Text>
          <View style={styles.swapRow}>
            <View style={styles.swapSide}>
              <Text style={styles.swapName} numberOfLines={1}>{s.requester_name}</Text>
              <View style={styles.shiftBubble}>
                <Text style={styles.shiftBubbleText}>{s.requester_shift_code ?? "—"}</Text>
              </View>
            </View>
            <Text style={styles.swapArrow}>⇄</Text>
            <View style={styles.swapSide}>
              <Text style={styles.swapName} numberOfLines={1}>{s.target_name}</Text>
              <View style={styles.shiftBubble}>
                <Text style={styles.shiftBubbleText}>{s.target_shift_code ?? "—"}</Text>
              </View>
            </View>
          </View>
          {s.reason ? <Text style={styles.cardMeta}>{s.reason}</Text> : null}
          <View style={styles.actionRow}>
            <BigButton
              testID={`swap-reject-${s.id}`}
              label={t("approvals.reject")}
              variant="danger"
              disabled={acting}
              onPress={() => setRejectTarget({ kind: "swap", id: s.id })}
              style={{ flex: 1 }}
            />
            <BigButton
              testID={`swap-approve-${s.id}`}
              label={t("approvals.approve")}
              variant="success"
              disabled={acting}
              onPress={() => void actSwap(s, true)}
              style={{ flex: 1 }}
            />
          </View>
        </View>
      );
    }
    if (segment === "incidents") {
      const inc = item as Incident;
      const def = categoryDef(inc.category);
      const Icon = def.icon;
      return (
        <Pressable
          testID={`approval-incident-${inc.id}`}
          onPress={() => router.push(`/incident/${inc.id}`)}
          style={({ pressed }) => [styles.card, { opacity: pressed ? 0.85 : 1 }]}
        >
          <View style={[styles.incIcon, { backgroundColor: `${def.tint}18` }]}>
            <Icon size={24} color={def.tint} strokeWidth={2.2} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.cardTitle} numberOfLines={1}>{t(def.tKey)}</Text>
            <Text style={styles.cardMeta}>
              {deptName(inc.department_code)} · {formatDateTime(inc.created_at)}
            </Text>
          </View>
          <StatusChip status={inc.status} />
        </Pressable>
      );
    }
    const rec = item as FlaggedAttendance;
    const reasonText = rec.flagged_reason?.includes("gps_missing")
      ? t("att.reasonGps")
      : rec.flagged_reason?.includes("outside_geofence")
        ? t("att.reasonGeofence")
        : (rec.flagged_reason ?? "");
    return (
      <View style={styles.regCard} testID={`approval-att-${rec.id}`}>
        <View style={styles.regTop}>
          <Image source={{ uri: resolveUri(rec.selfie_key) }} style={styles.attSelfie} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.cardTitle} numberOfLines={1}>
              {rec.employee_name} · {rec.emp_id}
            </Text>
            <Text style={styles.cardMeta}>
              {deptName(rec.department_code)} · {dayjs(rec.date).format("DD/MM")} ·{" "}
              {formatTime(rec.punch_in_at)}
            </Text>
            <View style={styles.reasonChip}>
              <Text style={styles.reasonChipText}>{reasonText}</Text>
            </View>
          </View>
        </View>
        <BigButton
          testID={`att-approve-${rec.id}`}
          label={t("approvals.approve")}
          variant="success"
          disabled={acting}
          onPress={() => void actAttendance(rec)}
        />
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="approvals-screen">
      <ScreenHeader title={t("approvals.title")} back={false} />

      <View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.segRow}>
          {segments.map((s) => {
            const active = segment === s.key;
            return (
              <Pressable
                key={s.key}
                testID={`segment-${s.key}`}
                onPress={() => setSegment(s.key)}
                style={[styles.seg, active && styles.segActive]}
              >
                <Text style={[styles.segText, active && styles.segTextActive]}>{s.label}</Text>
                {s.count > 0 ? (
                  <View style={[styles.segBadge, active && styles.segBadgeActive]}>
                    <Text style={styles.segBadgeText}>{s.count}</Text>
                  </View>
                ) : null}
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      {isTop ? (
        <View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.deptRow}>
            <Pressable
              testID="dept-filter-all"
              onPress={() => setDeptFilter(null)}
              style={[styles.deptChip, deptFilter === null && styles.deptChipActive]}
            >
              <Text style={[styles.deptChipText, deptFilter === null && styles.deptChipTextActive]}>
                {t("approvals.allDepts")}
              </Text>
            </Pressable>
            {(departments.data ?? []).map((d) => (
              <Pressable
                key={d.code}
                testID={`dept-filter-${d.code}`}
                onPress={() => setDeptFilter(d.code)}
                style={[styles.deptChip, deptFilter === d.code && styles.deptChipActive]}
              >
                <Text style={[styles.deptChipText, deptFilter === d.code && styles.deptChipTextActive]}>
                  {tri(d as unknown as Record<string, unknown>, "name")}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ) : null}

      {segment === "attendance" ? (
        <View style={styles.attFilterRow}>
          {(["today", "yesterday", "all"] as AttFilter[]).map((f) => (
            <Pressable
              key={f}
              testID={`att-filter-${f}`}
              onPress={() => setAttFilter(f)}
              style={[styles.deptChip, attFilter === f && styles.deptChipActive]}
            >
              <Text style={[styles.deptChipText, attFilter === f && styles.deptChipTextActive]}>
                {f === "today" ? t("common.today") : f === "yesterday" ? dayjs().subtract(1, "day").format("DD/MM") : t("approvals.allDepts")}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      <FlatList
        data={listData}
        keyExtractor={(item) => (item as { id: string }).id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        refreshing={loading}
        onRefresh={() => void loadAll()}
        ListEmptyComponent={empty}
      />

      <Modal
        visible={rejectTarget !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setRejectTarget(null)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard} testID="approvals-reject-modal">
            <Text style={styles.modalTitle}>{t("approvals.rejectReason")}</Text>
            <TextInput
              testID="approvals-reject-input"
              style={styles.reasonInput}
              value={reason}
              onChangeText={setReason}
              placeholder={t("forms.rejectionReason")}
              placeholderTextColor={colors.muted}
              multiline
              maxLength={300}
            />
            <View style={styles.actionRow}>
              <BigButton
                testID="approvals-reject-cancel"
                label={t("common.cancel")}
                variant="muted"
                onPress={() => {
                  setRejectTarget(null);
                  setReason("");
                }}
                style={{ flex: 1 }}
              />
              <BigButton
                testID="approvals-reject-confirm"
                label={t("approvals.reject")}
                variant="danger"
                disabled={reason.trim().length === 0}
                onPress={() => void confirmReject()}
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
  segRow: {
    gap: spacing.sm,
    paddingHorizontal: sizes.screenPadding,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
  },
  seg: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 48,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
  },
  segActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  segText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  segTextActive: { color: colors.onPrimary },
  segBadge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.danger,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 5,
  },
  segBadgeActive: { backgroundColor: "rgba(255,255,255,0.3)" },
  segBadgeText: { fontFamily: fonts.bold, fontSize: 12, color: "#FFFFFF" },
  deptRow: { gap: spacing.xs, paddingHorizontal: sizes.screenPadding, paddingVertical: spacing.xs },
  deptChip: {
    minHeight: 40,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    alignItems: "center",
    justifyContent: "center",
  },
  deptChipActive: { backgroundColor: colors.brandTertiary, borderColor: colors.primary },
  deptChipText: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.text },
  deptChipTextActive: { color: colors.primary, fontFamily: fonts.bold },
  attFilterRow: {
    flexDirection: "row",
    gap: spacing.xs,
    paddingHorizontal: sizes.screenPadding,
    paddingVertical: spacing.xs,
  },
  list: { padding: sizes.screenPadding, gap: spacing.md, flexGrow: 1, paddingTop: spacing.sm },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    minHeight: 76,
  },
  cardTitle: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  cardMeta: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  regCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  regTop: { flexDirection: "row", gap: spacing.md, alignItems: "center" },
  regSelfie: {
    width: 88,
    height: 88,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  regSelfieEmpty: { alignItems: "center", justifyContent: "center", backgroundColor: colors.brandTertiary },
  regInitial: { fontFamily: fonts.bold, fontSize: type.xxl, color: colors.primary },
  attSelfie: {
    width: 64,
    height: 64,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceTertiary,
  },
  actionRow: { flexDirection: "row", gap: spacing.md },
  swapRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  swapSide: { flex: 1, alignItems: "center", gap: spacing.xs },
  swapName: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  swapArrow: { fontFamily: fonts.bold, fontSize: type.xl, color: colors.accent },
  shiftBubble: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  shiftBubbleText: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.primary },
  incIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.sm,
    alignItems: "center",
    justifyContent: "center",
  },
  reasonChip: {
    alignSelf: "flex-start",
    backgroundColor: colors.warning,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 2,
    marginTop: 2,
  },
  reasonChipText: { fontFamily: fonts.semiBold, fontSize: 12, color: colors.onWarning },
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
});
