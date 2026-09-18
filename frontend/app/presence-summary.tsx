import { useLocalSearchParams } from "expo-router";
import { CalendarClock, ChevronLeft, ChevronRight, ShieldAlert } from "lucide-react-native";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import {
  presenceAlertAck,
  presenceAlertResolve,
  presenceAlerts,
  presenceShiftSummary,
  type PresenceAlertItem,
  type PresenceAlertList,
  type PresenceSummaryResp,
  type PresenceSummaryWorker,
} from "@/src/api/endpoints";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/** v1.0.26 Phase 2 — manager view: daily time-in-zone per worker + live
 * presence alerts (ack / resolve). Managers-only (rank <= 3). */

type Tab = "summary" | "alerts";

const ALERT_EMOJI: Record<string, string> = {
  outside_geofence: "🚨",
  gone_dark: "⚠️",
  low_battery: "🔋",
  unauthorized_zone: "⛔",
};

const ALERT_KEY: Record<string, string> = {
  outside_geofence: "presence.alertOutside",
  gone_dark: "presence.alertGoneDark",
  low_battery: "presence.alertLowBattery",
  unauthorized_zone: "presence.alertUnauthorized",
};

const todayIST = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

const shiftDay = (date: string, days: number) => {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

const fmtClock = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })
    : "—";

const fmtMin = (m: number | null | undefined) => {
  if (m === null || m === undefined) return "—";
  if (m >= 60) return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
  return `${m}m`;
};

function CoverageBar({ pct }: { pct: number | null }) {
  if (pct === null) return <Text style={styles.meta}>—</Text>;
  const tint = pct < 40 ? colors.danger : pct < 75 ? colors.warning : colors.success;
  return (
    <View style={styles.covRow}>
      <View style={styles.covTrack}>
        <View style={[styles.covFill, { width: `${pct}%`, backgroundColor: tint }]} />
      </View>
      <Text style={[styles.covPct, { color: tint }]}>{pct}%</Text>
    </View>
  );
}

export default function PresenceSummaryScreen() {
  const { t, i18n } = useTranslation();
  const params = useLocalSearchParams<{ tab?: string }>();
  const rank = useAuthStore((s) => s.profile?.role?.rank ?? 6);
  const [tab, setTab] = useState<Tab>(params.tab === "alerts" ? "alerts" : "summary");
  const [date, setDate] = useState(todayIST());
  const [summary, setSummary] = useState<PresenceSummaryResp | null>(null);
  const [alerts, setAlerts] = useState<PresenceAlertList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (tab === "summary") setSummary(await presenceShiftSummary(date));
      else setAlerts(await presenceAlerts("open"));
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [tab, date]);

  useEffect(() => {
    if (rank <= 3) void load();
  }, [load, rank]);

  const act = async (id: string, action: "ack" | "resolve") => {
    setBusy(id + action);
    try {
      if (action === "ack") await presenceAlertAck(id);
      else await presenceAlertResolve(id);
      await load();
    } catch {
      setError(true);
    } finally {
      setBusy("");
    }
  };

  if (rank > 3) {
    return (
      <SafeAreaView style={styles.safe} edges={[]} testID="presence-summary-screen">
        <ScreenHeader title={t("presence.summaryTitle")} backTo="/(tabs)/home" />
        <EmptyState icon={ShieldAlert} title={t("presence.managersOnly")} />
      </SafeAreaView>
    );
  }

  const zoneLabel = (z: { zone_en: string; zone_hi: string | null; zone_mr: string | null }) => {
    const lang = i18n.language;
    if (lang === "hi" && z.zone_hi) return z.zone_hi;
    if (lang === "mr" && z.zone_mr) return z.zone_mr;
    return z.zone_en;
  };

  const alertDetail = (a: PresenceAlertItem): string => {
    if (a.alert_type === "outside_geofence") return `${a.detail?.minutes ?? 0} ${t("presence.minOutside")}`;
    if (a.alert_type === "gone_dark") return `${a.detail?.minutes ?? 0} ${t("presence.minSilent")}`;
    if (a.alert_type === "low_battery") return `🔋 ${a.detail?.battery_pct ?? "?"}%`;
    return `${a.zone_en || a.zone_key || "?"}`;
  };

  const renderWorker = ({ item: w }: { item: PresenceSummaryWorker }) => (
    <View style={[styles.card, !w.tracked && { opacity: 0.55 }]} testID={`summary-worker-${w.emp_id}`}>
      <View style={styles.cardHead}>
        <View style={{ flex: 1 }}>
          <Text style={styles.name} numberOfLines={1}>{w.full_name}</Text>
          <Text style={styles.meta}>
            {w.emp_id} · {w.department_code || "—"} · {fmtClock(w.punch_in_at)} → {w.punch_out_at ? fmtClock(w.punch_out_at) : "…"}
          </Text>
        </View>
        {!w.tracked ? (
          <View style={styles.dimChip}><Text style={styles.dimChipText}>{t("presence.notTracked")}</Text></View>
        ) : null}
      </View>
      {w.tracked ? (
        <>
          <View style={styles.statRow}>
            <Text style={styles.statLabel}>{t("presence.coverage")}</Text>
            <CoverageBar pct={w.coverage_pct} />
            <Text style={styles.meta}>
              {fmtMin(w.tracked_min)} / {fmtMin(w.shift_min)}
            </Text>
          </View>
          <View style={styles.chipsWrap}>
            {w.zones.map((z) => (
              <View key={z.zone_key} style={styles.zoneChip}>
                <Text style={styles.zoneChipText}>{zoneLabel(z)} · {fmtMin(z.minutes)}</Text>
              </View>
            ))}
            {w.gps_inside_min > 0 ? (
              <View style={styles.zoneChip}>
                <Text style={styles.zoneChipText}>{t("presence.insideGps")} · {fmtMin(w.gps_inside_min)}</Text>
              </View>
            ) : null}
            {w.outside_min > 0 ? (
              <View style={[styles.zoneChip, styles.redChip]}>
                <Text style={[styles.zoneChipText, { color: colors.danger }]}>
                  {t("presence.outside")} · {fmtMin(w.outside_min)}
                </Text>
              </View>
            ) : null}
          </View>
        </>
      ) : null}
    </View>
  );

  const renderAlert = ({ item: a }: { item: PresenceAlertItem }) => (
    <View style={[styles.card, a.status === "active" && styles.cardActive]} testID={`alert-card-${a.id}`}>
      <Text style={styles.alertTitle}>
        {ALERT_EMOJI[a.alert_type]} {t(ALERT_KEY[a.alert_type] ?? "presence.alertOutside")}
      </Text>
      <Text style={styles.name}>{a.full_name}</Text>
      <Text style={styles.meta}>
        {a.emp_id} · {a.department_code || "—"} · {alertDetail(a)} · {t("presence.since")} {fmtClock(a.first_seen_at)}
      </Text>
      <View style={styles.btnRow}>
        {a.status === "active" ? (
          <Pressable
            testID={`alert-ack-${a.id}`}
            accessibilityRole="button"
            disabled={busy === `${a.id}ack`}
            onPress={() => void act(a.id, "ack")}
            style={({ pressed }) => [styles.btn, styles.btnGhost, { opacity: pressed ? 0.85 : 1 }]}
          >
            <Text style={styles.btnGhostText}>{t("presence.ack")}</Text>
          </Pressable>
        ) : (
          <View style={styles.dimChip}><Text style={styles.dimChipText}>{t("presence.acked")}</Text></View>
        )}
        <Pressable
          testID={`alert-resolve-${a.id}`}
          accessibilityRole="button"
          disabled={busy === `${a.id}resolve`}
          onPress={() => void act(a.id, "resolve")}
          style={({ pressed }) => [styles.btn, styles.btnPrimary, { opacity: pressed ? 0.85 : 1 }]}
        >
          <Text style={styles.btnPrimaryText}>{t("presence.resolve")}</Text>
        </Pressable>
      </View>
    </View>
  );

  const counts = summary?.counts;
  const openCount = alerts?.open_total ?? 0;

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="presence-summary-screen">
      <ScreenHeader title={t("presence.summaryTitle")} backTo="/(tabs)/home" />

      <View style={styles.toggleRow}>
        {(["summary", "alerts"] as Tab[]).map((k) => (
          <Pressable
            key={k}
            testID={`presence-tab-${k}`}
            accessibilityRole="button"
            onPress={() => setTab(k)}
            style={[styles.toggle, tab === k && styles.toggleActive]}
          >
            <Text style={[styles.toggleText, tab === k && styles.toggleTextActive]}>
              {t(k === "summary" ? "presence.tabSummary" : "presence.tabAlerts")}
              {k === "alerts" && openCount > 0 ? ` (${openCount})` : ""}
            </Text>
          </Pressable>
        ))}
      </View>

      {tab === "summary" ? (
        <>
          <View style={styles.dateRow}>
            <Pressable
              testID="summary-prev-day"
              accessibilityRole="button"
              onPress={() => setDate(shiftDay(date, -1))}
              style={styles.dateBtn}
            >
              <ChevronLeft size={24} color={colors.text} strokeWidth={2.4} />
            </Pressable>
            <View style={styles.dateMid}>
              <CalendarClock size={18} color={colors.muted} strokeWidth={2.2} />
              <Text style={styles.dateText} testID="summary-date">
                {date === todayIST() ? t("presence.today") : date}
              </Text>
            </View>
            <Pressable
              testID="summary-next-day"
              accessibilityRole="button"
              disabled={date >= todayIST()}
              onPress={() => setDate(shiftDay(date, 1))}
              style={[styles.dateBtn, date >= todayIST() && { opacity: 0.3 }]}
            >
              <ChevronRight size={24} color={colors.text} strokeWidth={2.4} />
            </Pressable>
          </View>
          {counts ? (
            <Text style={styles.countsLine} testID="summary-counts">
              {counts.tracked}/{counts.workers} {t("presence.trackedShort")} · {t("presence.coverage")} {counts.avg_coverage_pct}%
            </Text>
          ) : null}
          {error && !summary ? (
            <ErrorRetry onRetry={() => void load()} />
          ) : summary && !summary.enabled ? (
            <EmptyState icon={ShieldAlert} title={t("presence.disabled")} />
          ) : (
            <FlatList
              data={summary?.workers ?? []}
              keyExtractor={(w) => w.id}
              renderItem={renderWorker}
              contentContainerStyle={styles.list}
              refreshing={loading}
              onRefresh={() => void load()}
              ListEmptyComponent={
                loading ? (
                  <ActivityIndicator color={colors.primary} style={{ marginTop: spacing.xl }} />
                ) : (
                  <EmptyState icon={CalendarClock} title={t("presence.noSummary")} />
                )
              }
            />
          )}
        </>
      ) : error && !alerts ? (
        <ErrorRetry onRetry={() => void load()} />
      ) : (
        <FlatList
          data={alerts?.alerts ?? []}
          keyExtractor={(a) => a.id}
          renderItem={renderAlert}
          contentContainerStyle={styles.list}
          refreshing={loading}
          onRefresh={() => void load()}
          ListEmptyComponent={
            loading ? (
              <ActivityIndicator color={colors.primary} style={{ marginTop: spacing.xl }} />
            ) : (
              <EmptyState icon={ShieldAlert} title={t("presence.noAlerts")} />
            )
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  list: { padding: sizes.screenPadding, gap: spacing.md, flexGrow: 1 },
  toggleRow: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: sizes.screenPadding,
    paddingTop: spacing.md,
  },
  toggle: {
    flex: 1,
    height: 48,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
  },
  toggleActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  toggleText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  toggleTextActive: { color: colors.onPrimary },
  dateRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: sizes.screenPadding,
    paddingTop: spacing.md,
  },
  dateBtn: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  dateMid: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dateText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  countsLine: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.muted,
    paddingHorizontal: sizes.screenPadding,
    paddingTop: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  cardActive: { borderColor: colors.danger, borderWidth: 2 },
  cardHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  name: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text },
  meta: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  statRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  statLabel: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.muted },
  covRow: { flexDirection: "row", alignItems: "center", gap: 6, flex: 1 },
  covTrack: {
    flex: 1,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  covFill: { height: "100%", borderRadius: 4 },
  covPct: { fontFamily: fonts.bold, fontSize: type.sm },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  zoneChip: {
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
  },
  redChip: { borderColor: colors.danger },
  zoneChipText: { fontFamily: fonts.semiBold, fontSize: 12, color: colors.text },
  dimChip: {
    borderRadius: radius.pill,
    backgroundColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
  },
  dimChipText: { fontFamily: fonts.semiBold, fontSize: 12, color: colors.muted },
  alertTitle: { fontFamily: fonts.bold, fontSize: type.base, color: colors.danger },
  btnRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.xs },
  btn: {
    minHeight: 44,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
    justifyContent: "center",
  },
  btnGhost: { borderWidth: 2, borderColor: colors.border, backgroundColor: colors.surface },
  btnGhostText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  btnPrimary: { backgroundColor: colors.primary },
  btnPrimaryText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.onPrimary },
});
