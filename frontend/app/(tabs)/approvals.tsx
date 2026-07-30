import dayjs from "dayjs";
import { useAudioPlayer } from "expo-audio";
import { useFocusEffect, useRouter } from "expo-router";
import { ClipboardCheck, Play, Square } from "lucide-react-native";
import React, { useCallback, useEffect, useState } from "react";
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
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useTranslation } from "react-i18next";

import { ApiError, fileUrl } from "@/src/api/client";
import {
  approveAttendance,
  rejectAttendance,
  approveEmployee,
  decideRegularization,
  decideSwap,
  flaggedAttendance,
  listDepartments,
  listIncidents,
  listRegularizations,
  listSubmissions,
  pendingEmployees,
  pendingSwaps,
  rejectEmployee,
  type RegularizationItem,
} from "@/src/api/endpoints";
import type {
  DepartmentItem,
  EmployeeProfile,
  FlaggedAttendance,
  Incident,
  PendingRegistration,
  SubmissionItem,
  SwapRequest,
} from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { EmptyState } from "@/src/components/EmptyState";
import { MediaViewerModal } from "@/src/components/MediaCard";
import { MapPreview } from "@/src/components/MapPreview";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { SeverityChip } from "@/src/components/SeverityChip";
import { SkeletonRows } from "@/src/components/Skeleton";
import { showToast } from "@/src/components/Toast";
import { StatusChip } from "@/src/components/StatusChip";
import { categoryDef } from "@/src/constants/categories";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useApprovalsStore, type ApprovalCounts } from "@/src/stores/approvalsStore";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { formatDateTime, formatTime, isOlderThan24h, timeAgo } from "@/src/utils/format";
import { storage } from "@/src/utils/storage";

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
  // v1.0.21 attendance disputes (regularization requests) — TO queue
  const [disputes, setDisputes] = useState<RegularizationItem[]>([]);
  const voicePlayer = useAudioPlayer();
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);

  const toggleDisputeVoice = (d: RegularizationItem) => {
    if (!d.voice_note_url) return;
    if (playingVoiceId === d.id) {
      voicePlayer.pause();
      setPlayingVoiceId(null);
      return;
    }
    voicePlayer.replace({ uri: resolveUri(d.voice_note_url) });
    voicePlayer.seekTo(0);
    voicePlayer.play();
    setPlayingVoiceId(d.id);
  };
  const [approveTarget, setApproveTarget] = useState<EmployeeProfile | null>(null);
  const [apDept, setApDept] = useState<string | null>(null);
  const [apRole, setApRole] = useState("Worker");
  const [apEmpId, setApEmpId] = useState("");
  const [viewImg, setViewImg] = useState<string | null>(null);

  // stale-while-revalidate: hydrate the last-seen lists instantly, refresh on focus
  useEffect(() => {
    void (async () => {
      const raw = await storage.getItem<string>("hogo.cache.approvals", "");
      if (!raw) return;
      try {
        const c = JSON.parse(raw) as Record<string, unknown[]>;
        setSubs((p) => (p.length ? p : ((c.subs ?? []) as SubmissionItem[])));
        setRegs((p) => (p.length ? p : ((c.regs ?? []) as EmployeeProfile[])));
        setSwaps((p) => (p.length ? p : ((c.swaps ?? []) as SwapRequest[])));
        setIncidents((p) => (p.length ? p : ((c.incidents ?? []) as Incident[])));
        setFlagged((p) => (p.length ? p : ((c.flagged ?? []) as FlaggedAttendance[])));
      } catch {
        // corrupt cache — ignore
      }
    })();
  }, []);

  const departments = useCachedFetch<DepartmentItem[]>("departments", listDepartments);

  const attDate =
    attFilter === "today"
      ? dayjs().format("YYYY-MM-DD")
      : attFilter === "yesterday"
        ? dayjs().subtract(1, "day").format("YYYY-MM-DD")
        : undefined;

  const loadAll = useCallback(async () => {
    setLoading(true);
    const [sub, esc, reg, swp, incSub, incEsc, att, disp] = await Promise.allSettled([
      listSubmissions({ status: "submitted" }),
      listSubmissions({ status: "escalated" }),
      pendingEmployees(),
      pendingSwaps(),
      listIncidents({ status: "submitted" }),
      listIncidents({ status: "escalated" }),
      showAttendance ? flaggedAttendance(attDate) : Promise.resolve([]),
      showAttendance ? listRegularizations("open") : Promise.resolve([]),
    ]);
    setSubs([
      ...(sub.status === "fulfilled" ? sub.value.items : []),
      ...(esc.status === "fulfilled" ? esc.value.items : []),
    ]);
    setRegs(reg.status === "fulfilled" ? reg.value : []);
    setSwaps(swp.status === "fulfilled" ? swp.value : []);
    const incItems = [
      ...(incSub.status === "fulfilled" ? incSub.value : []),
      ...(incEsc.status === "fulfilled" ? incEsc.value : []),
    ];
    // critical first, then high, then normal
    const sevRank: Record<string, number> = { critical: 0, high: 1, normal: 2 };
    incItems.sort((a, b) => (sevRank[a.severity] ?? 2) - (sevRank[b.severity] ?? 2));
    setIncidents(incItems);
    setFlagged(att.status === "fulfilled" ? (att.value as FlaggedAttendance[]) : []);
    setDisputes(disp.status === "fulfilled" ? (disp.value as RegularizationItem[]) : []);
    setLoading(false);
    void refreshCounts(showAttendance);
    void storage.setItem(
      "hogo.cache.approvals",
      JSON.stringify({
        subs: [
          ...(sub.status === "fulfilled" ? sub.value.items : []),
          ...(esc.status === "fulfilled" ? esc.value.items : []),
        ],
        regs: reg.status === "fulfilled" ? reg.value : [],
        swaps: swp.status === "fulfilled" ? swp.value : [],
        incidents: incItems,
        flagged: att.status === "fulfilled" ? att.value : [],
      }),
    );
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

  const actReg = (
    emp: EmployeeProfile,
    approve: boolean,
    rejectReason?: string,
    assignment?: { department_code: string; role_code: string; emp_id: string },
  ) =>
    optimistic(
      "regs",
      () => {
        setRegs((prev) => prev.filter((r) => r.id !== emp.id));
        return regs;
      },
      (snap) => setRegs(snap),
      () =>
        approve && assignment
          ? approveEmployee(emp.id, assignment)
          : rejectEmployee(emp.id, rejectReason ?? ""),
    );

  const confirmApprove = async () => {
    if (!approveTarget || !apDept || apEmpId.trim().length === 0) return;
    const emp = approveTarget;
    const assignment = { department_code: apDept, role_code: apRole, emp_id: apEmpId.trim() };
    setApproveTarget(null);
    await actReg(emp, true, undefined, assignment);
  };

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

  const actAttendance = (rec: FlaggedAttendance, approve = true) =>
    optimistic(
      "attendance",
      () => {
        setFlagged((prev) => prev.filter((f) => f.id !== rec.id));
        return flagged;
      },
      (snap) => setFlagged(snap),
      () => (approve ? approveAttendance(rec.id) : rejectAttendance(rec.id)),
    );

  const actDispute = async (d: RegularizationItem, approve: boolean) => {
    if (acting) return;
    setActing(true);
    try {
      await decideRegularization(d.id, approve ? "approve" : "reject");
      setDisputes((prev) => prev.filter((x) => x.id !== d.id));
      // a decided dispute also resolves the underlying flagged punch
      setFlagged((prev) => prev.filter((f) => f.id !== d.attendance.id));
      showToast(t("approvals.actionDone"), "success");
    } catch (e) {
      showToast(
        e instanceof ApiError && e.status === 0 ? t("errors.network") : t("errors.server"),
        "error",
      );
    } finally {
      setActing(false);
    }
  };

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
            : [...disputes, ...byDept(flagged)];

  const renderItem = ({ item }: { item: unknown }) => {
    if (segment === "forms") {
      const s = item as SubmissionItem;
      return (
        <Pressable
          testID={`approval-sub-${s.id}`}
          onPress={() => router.push({ pathname: "/submission/[id]", params: { id: s.id } })}
          style={({ pressed }) => [styles.card, { opacity: pressed ? 0.85 : 1 }]}
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.cardTitle} numberOfLines={1}>
              {tri(s as unknown as Record<string, unknown>, "form_title") || s.form_code}
            </Text>
            <Text style={styles.cardMeta} numberOfLines={1}>
              {s.submitted_by_name ?? ""} · {deptName(s.department_code)}
            </Text>
            <Text style={styles.cardMeta}>
              {timeAgo(s.created_at)}
              {s.status === "submitted" && isOlderThan24h(s.created_at) ? (
                <Text style={styles.agingChip}>  ⏰ 24h+</Text>
              ) : null}
            </Text>
          </View>
          <StatusChip status={s.status} />
        </Pressable>
      );
    }
    if (segment === "regs") {
      const emp = item as PendingRegistration;
      const dup = emp.duplicate_hints ?? [];
      return (
        <View style={styles.regCard} testID={`approval-reg-${emp.id}`}>
          <View style={styles.regTop}>
            {emp.selfie_url ? (
              <Pressable
                onPress={() => setViewImg(resolveUri(emp.selfie_url as string))}
                accessibilityRole="imagebutton"
                accessibilityLabel={t("media.viewFull")}
                testID={`reg-selfie-${emp.id}`}
              >
                <Image source={{ uri: resolveUri(emp.selfie_url) }} style={styles.regSelfie} />
              </Pressable>
            ) : (
              <View style={[styles.regSelfie, styles.regSelfieEmpty]}>
                <Text style={styles.regInitial}>{emp.full_name.charAt(0)}</Text>
              </View>
            )}
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.cardTitle}>{emp.full_name}</Text>
              <Text style={styles.cardMeta}>{emp.phone}</Text>
              <Text style={styles.cardMeta}>
                {emp.department_code
                  ? t("approvals.wantsToJoin", { dept: deptName(emp.department_code) })
                  : t("approvals.newJoinee")}
              </Text>
              <Text style={styles.cardMeta}>
                🆔 {emp.emp_id || emp.suggested_emp_id}
              </Text>
            </View>
          </View>

          {/* v1.0.20 registration evidence for the approver */}
          <View style={styles.regEvidence} testID={`reg-evidence-${emp.id}`}>
            {emp.created_at ? (
              <Text style={styles.regInfoLine}>
                🕐 {formatDateTime(emp.created_at)} · {timeAgo(emp.created_at)}
              </Text>
            ) : null}
            {emp.reg_lat != null && emp.reg_lng != null ? (
              <>
                <View style={styles.regChipsRow}>
                  <View
                    style={[styles.geoChip, emp.reg_inside_geofence ? styles.geoChipIn : styles.geoChipOut]}
                    testID={`reg-geofence-chip-${emp.id}`}
                  >
                    <Text style={emp.reg_inside_geofence ? styles.geoChipTextIn : styles.geoChipTextOut}>
                      {emp.reg_inside_geofence
                        ? `✓ ${t("approvals.insideFactory")}`
                        : `✗ ${t("approvals.outsideFactory")}`}
                    </Text>
                  </View>
                  {emp.reg_zone ? <Text style={styles.regInfoMuted}>📡 {emp.reg_zone}</Text> : null}
                </View>
                {emp.reg_address ? (
                  <Text style={styles.regInfoMuted} numberOfLines={2}>
                    {emp.reg_address}
                  </Text>
                ) : null}
                <Text style={styles.regCoords}>
                  {emp.reg_lat.toFixed(5)}, {emp.reg_lng.toFixed(5)}
                </Text>
                <MapPreview lat={emp.reg_lat} lng={emp.reg_lng} testID={`reg-map-${emp.id}`} />
              </>
            ) : (
              <Text style={styles.regInfoMuted}>📍 {t("approvals.noLocation")}</Text>
            )}
            <View style={styles.regChipsRow}>
              <Text style={styles.regInfoLine}>
                {emp.reg_face_count != null && emp.reg_face_count > 0
                  ? `✅ ${t("approvals.faceOk")}`
                  : `⚠️ ${t("approvals.faceUnknown")}`}
              </Text>
              {emp.reg_device ? (
                <Text style={styles.regInfoMuted} numberOfLines={1}>
                  📱 {emp.reg_device}
                  {emp.reg_app_version ? ` · v${emp.reg_app_version}` : ""}
                </Text>
              ) : null}
            </View>
            {dup.length > 0 ? (
              <View style={styles.dupWarn} testID={`reg-dup-warning-${emp.id}`}>
                <Text style={styles.dupWarnTitle}>⚠️ {t("approvals.possibleDuplicate")}</Text>
                {dup.map((h) => (
                  <Text key={h.emp_id} style={styles.dupWarnLine}>
                    {h.full_name} · {h.emp_id}
                    {h.phone ? ` · ${h.phone}` : ""}
                  </Text>
                ))}
              </View>
            ) : null}
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
              onPress={() => {
                setApDept(emp.department_code ?? null);
                setApRole("Worker");
                setApEmpId(emp.emp_id ?? "");
                setApproveTarget(emp);
              }}
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
          onPress={() => router.push({ pathname: "/incident/[id]", params: { id: inc.id } })}
          style={({ pressed }) => [styles.card, { opacity: pressed ? 0.85 : 1 }]}
        >
          <View style={[styles.incIcon, { backgroundColor: `${def.tint}18` }]}>
            <Icon size={24} color={def.tint} strokeWidth={2.2} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={styles.cardTitle} numberOfLines={1}>{t(def.tKey)}</Text>
            <Text style={styles.cardMeta}>
              {deptName(inc.department_code)} · {timeAgo(inc.created_at)}
              {inc.status !== "resolved" && isOlderThan24h(inc.created_at) ? (
                <Text style={styles.agingChip}>  ⏰ 24h+</Text>
              ) : null}
            </Text>
          </View>
          <View style={{ alignItems: "flex-end", gap: 4 }}>
            <StatusChip status={inc.status} />
            {inc.severity !== "normal" ? (
              <SeverityChip severity={inc.severity} testID={`severity-${inc.id}`} />
            ) : null}
          </View>
        </Pressable>
      );
    }
    // v1.0.21: attendance dispute card — worker's request + original evidence
    if (segment === "attendance" && (item as RegularizationItem).attendance !== undefined) {
      const d = item as RegularizationItem;
      const a = d.attendance;
      return (
        <View style={[styles.regCard, styles.disputeCard]} testID={`dispute-card-${d.id}`}>
          <View style={styles.disputeBadge}>
            <Text style={styles.disputeBadgeText}>✋ {t("approvals.dispute")}</Text>
          </View>
          <View style={styles.regTop}>
            {a.selfie_url ? (
              <Pressable
                onPress={() => setViewImg(resolveUri(a.selfie_url as string))}
                accessibilityRole="imagebutton"
                accessibilityLabel={t("media.viewFull")}
              >
                <Image source={{ uri: resolveUri(a.selfie_url) }} style={styles.attSelfie} />
              </Pressable>
            ) : null}
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={styles.cardTitle} numberOfLines={1}>
                {d.employee_name} · {d.emp_id}
              </Text>
              <Text style={styles.cardMeta}>
                {deptName(d.department_code ?? "")} · {dayjs(a.date).format("DD/MM")} ·{" "}
                {formatTime(a.punch_in_at)}
                {a.ble_zone ? ` · ${a.ble_zone}` : ""}
              </Text>
              <View style={styles.reasonChip}>
                <Text style={styles.reasonChipText}>{a.flagged_reason ?? ""}</Text>
              </View>
            </View>
          </View>
          {d.text_note ? (
            <Text style={styles.disputeNote}>
              💬 {t("approvals.workerSays")}: {d.text_note}
            </Text>
          ) : null}
          {d.voice_note_url ? (
            <Pressable
              testID={`dispute-voice-${d.id}`}
              accessibilityRole="button"
              onPress={() => toggleDisputeVoice(d)}
              style={({ pressed }) => [styles.voiceBtn, { opacity: pressed ? 0.8 : 1 }]}
            >
              {playingVoiceId === d.id ? (
                <Square size={16} color={colors.primary} strokeWidth={2.4} fill={colors.primary} />
              ) : (
                <Play size={16} color={colors.primary} strokeWidth={2.4} />
              )}
              <Text style={styles.voiceBtnText}>{t("approvals.voiceNote")}</Text>
            </Pressable>
          ) : null}
          <View style={{ flexDirection: "row", gap: 10 }}>
            <View style={{ flex: 1 }}>
              <BigButton
                testID={`dispute-reject-${d.id}`}
                label={t("approvals.reject")}
                variant="danger"
                disabled={acting}
                onPress={() => void actDispute(d, false)}
              />
            </View>
            <View style={{ flex: 1 }}>
              <BigButton
                testID={`dispute-approve-${d.id}`}
                label={t("approvals.approve")}
                variant="success"
                disabled={acting}
                onPress={() => void actDispute(d, true)}
              />
            </View>
          </View>
        </View>
      );
    }
    const rec = item as FlaggedAttendance;
    const isFaceMismatch = rec.flagged_reason === "face_mismatch";
    const reasonText = isFaceMismatch
      ? t("att.reasonFace")
      : rec.flagged_reason === "no_punch_out"
        ? t("att.reasonNoPunchOut")
        : rec.flagged_reason === "no_beacon_gps_only"
          ? t("att.reasonNoBeacon")
          : rec.flagged_reason === "no_beacon_no_gps"
            ? t("att.reasonNoBeaconNoGps")
            : rec.flagged_reason?.includes("gps_missing")
              ? t("att.reasonGps")
              : rec.flagged_reason?.includes("outside_geofence")
                ? t("att.reasonGeofence")
                : (rec.flagged_reason ?? "");
    return (
      <View style={styles.regCard} testID={`approval-att-${rec.id}`}>
        <View style={styles.regTop}>
          {!isFaceMismatch ? (
            <Pressable
              onPress={() => setViewImg(rec.selfie_url ? resolveUri(rec.selfie_url) : resolveUri(rec.selfie_key))}
              accessibilityRole="imagebutton"
              accessibilityLabel={t("media.viewFull")}
            >
              <Image
                source={{ uri: rec.selfie_url ? resolveUri(rec.selfie_url) : resolveUri(rec.selfie_key) }}
                style={styles.attSelfie}
              />
            </Pressable>
          ) : null}
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
        {isFaceMismatch ? (
          <View testID={`face-compare-${rec.id}`}>
            <View style={styles.faceRow}>
              <View style={styles.faceCol}>
                {rec.reference_selfie_url ? (
                  <Pressable
                    style={{ width: "100%" }}
                    onPress={() => setViewImg(resolveUri(rec.reference_selfie_url as string))}
                    accessibilityRole="imagebutton"
                    accessibilityLabel={t("media.viewFull")}
                  >
                    <Image source={{ uri: resolveUri(rec.reference_selfie_url) }} style={styles.faceImg} />
                  </Pressable>
                ) : (
                  <View style={[styles.faceImg, styles.faceImgEmpty]} />
                )}
                <Text style={styles.faceLabel}>{t("att.refPhoto")}</Text>
              </View>
              <View style={styles.faceCol}>
                {rec.selfie_url ? (
                  <Pressable
                    style={{ width: "100%" }}
                    onPress={() => setViewImg(resolveUri(rec.selfie_url as string))}
                    accessibilityRole="imagebutton"
                    accessibilityLabel={t("media.viewFull")}
                  >
                    <Image source={{ uri: resolveUri(rec.selfie_url) }} style={styles.faceImg} />
                  </Pressable>
                ) : (
                  <View style={[styles.faceImg, styles.faceImgEmpty]} />
                )}
                <Text style={styles.faceLabel}>{t("att.punchPhoto")}</Text>
              </View>
            </View>
            {rec.face_match_score !== null ? (
              <View style={styles.scoreChip} testID={`face-score-${rec.id}`}>
                <Text style={styles.scoreChipText}>
                  {t("att.faceScore", { s: Math.round(rec.face_match_score) })}
                </Text>
              </View>
            ) : null}
          </View>
        ) : null}
        <View style={{ flexDirection: "row", gap: 10 }}>
          <View style={{ flex: 1 }}>
            <BigButton
              testID={`att-reject-${rec.id}`}
              label={t("approvals.reject")}
              variant="danger"
              disabled={acting}
              onPress={() => void actAttendance(rec, false)}
            />
          </View>
          <View style={{ flex: 1 }}>
            <BigButton
              testID={`att-approve-${rec.id}`}
              label={t("approvals.approve")}
              variant="success"
              disabled={acting}
              onPress={() => void actAttendance(rec)}
            />
          </View>
        </View>
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
        ListEmptyComponent={loading && listData.length === 0 ? <SkeletonRows /> : empty}
      />

      <Modal
        visible={rejectTarget !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setRejectTarget(null)}
      >
        <KeyboardAvoidingView behavior="padding" style={styles.modalBackdrop}>
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
        </KeyboardAvoidingView>
      </Modal>

      <Modal
        visible={approveTarget !== null}
        transparent
        animationType="slide"
        onRequestClose={() => setApproveTarget(null)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard} testID="approvals-approve-modal">
            <Text style={styles.modalTitle}>
              {t("approvals.approveTitle", { name: approveTarget?.full_name ?? "" })}
            </Text>

            <Text style={styles.assignLabel}>{t("approvals.assignDept")}</Text>
            <ScrollView style={styles.assignDeptList} nestedScrollEnabled>
              {(departments.data ?? []).map((d) => {
                const active = apDept === d.code;
                return (
                  <Pressable
                    key={d.code}
                    testID={`assign-dept-${d.code}`}
                    onPress={() => setApDept(d.code)}
                    style={[styles.assignRow, active && styles.assignRowActive]}
                  >
                    <Text style={[styles.assignRowText, active && { color: colors.primary }]}>
                      {tri(d as unknown as Record<string, unknown>, "name")}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>

            <Text style={styles.assignLabel}>{t("approvals.assignRole")}</Text>
            <View style={styles.roleRow}>
              {["Worker", "Staff", "Clerk", "Manager"].map((r) => (
                <Pressable
                  key={r}
                  testID={`assign-role-${r}`}
                  onPress={() => setApRole(r)}
                  style={[styles.deptChip, apRole === r && styles.deptChipActive]}
                >
                  <Text style={[styles.deptChipText, apRole === r && styles.deptChipTextActive]}>
                    {r}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.assignLabel}>{t("approvals.empId")}</Text>
            <TextInput
              testID="assign-empid-input"
              style={styles.empIdInput}
              value={apEmpId}
              onChangeText={setApEmpId}
              placeholder={t("approvals.empId")}
              placeholderTextColor={colors.muted}
              autoCapitalize="characters"
              maxLength={20}
            />

            <View style={styles.actionRow}>
              <BigButton
                testID="approvals-approve-cancel"
                label={t("common.cancel")}
                variant="muted"
                onPress={() => setApproveTarget(null)}
                style={{ flex: 1 }}
              />
              <BigButton
                testID="approvals-approve-confirm"
                label={t("approvals.approve")}
                variant="success"
                disabled={!apDept || apEmpId.trim().length === 0}
                onPress={() => void confirmApprove()}
                style={{ flex: 1 }}
              />
            </View>
          </View>
        </View>
      </Modal>
      <MediaViewerModal uri={viewImg} kind="photo" onClose={() => setViewImg(null)} />
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
  agingChip: { fontFamily: fonts.bold, fontSize: type.sm, color: colors.danger },
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
  // v1.0.20 registration evidence block
  regEvidence: {
    gap: 6,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
    marginTop: spacing.sm,
  },
  regInfoLine: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.text },
  regInfoMuted: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, flexShrink: 1 },
  regCoords: { fontFamily: fonts.regular, fontSize: 12, color: colors.muted },
  regChipsRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
  geoChip: { borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: 3, borderWidth: 1 },
  geoChipIn: { backgroundColor: "rgba(46,125,50,0.10)", borderColor: colors.success },
  geoChipOut: { backgroundColor: "rgba(217,64,89,0.10)", borderColor: colors.danger },
  geoChipTextIn: { fontFamily: fonts.semiBold, fontSize: 12, color: colors.success },
  geoChipTextOut: { fontFamily: fonts.semiBold, fontSize: 12, color: colors.danger },
  dupWarn: {
    backgroundColor: "rgba(217,64,89,0.08)",
    borderColor: colors.danger,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.sm,
    gap: 2,
  },
  dupWarnTitle: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.danger },
  dupWarnLine: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.text },
  attSelfie: {
    width: 64,
    height: 64,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceTertiary,
  },
  disputeCard: { borderColor: colors.warning, borderWidth: 1.5 },
  disputeBadge: {
    alignSelf: "flex-start",
    backgroundColor: `${colors.warning}22`,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  disputeBadgeText: { fontFamily: fonts.bold, fontSize: 12, color: colors.warning },
  disputeNote: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.text },
  voiceBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    minHeight: 40,
  },
  voiceBtnText: { fontFamily: fonts.bold, fontSize: type.sm, color: colors.primary },
  faceRow: { flexDirection: "row", gap: spacing.md, marginBottom: spacing.sm },
  faceCol: { flex: 1, alignItems: "center", gap: 4 },
  faceImg: {
    width: "100%",
    aspectRatio: 1,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  faceImgEmpty: { borderWidth: 1, borderColor: colors.border },
  faceLabel: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  scoreChip: {
    alignSelf: "center",
    backgroundColor: "#FDE3E7",
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 4,
  },
  scoreChipText: { fontFamily: fonts.bold, fontSize: type.sm, color: colors.danger },
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
  assignLabel: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.muted,
    marginTop: spacing.sm,
  },
  assignDeptList: {
    maxHeight: 180,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  assignRow: {
    minHeight: sizes.touchTarget,
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
  },
  assignRowActive: { backgroundColor: colors.brandTertiary },
  assignRowText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  roleRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  empIdInput: {
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.text,
  },
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
