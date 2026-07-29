import { useRouter } from "expo-router";
import {
  AlertTriangle,
  Bell,
  BookOpen,
  Building2,
  Car,
  CheckSquare,
  ClipboardList,
  Clock,
  FileText,
  Fingerprint,
  LogIn,
  Megaphone,
  Search,
  Shield,
  Truck,
  UserPlus,
  Users,
  type LucideIcon,
} from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import type { HomeWidget, HomeWidgetItem } from "@/src/api/endpoints";
import { colors, fonts, radius, shadow, spacing, type } from "@/src/theme/tokens";

/** Whitelisted icon vocabulary for config-driven homes (keeps the bundle lean
 * and a bad config harmless — unknown names fall back to ClipboardList). */
const ICONS: Record<string, LucideIcon> = {
  AlertTriangle,
  Bell,
  BookOpen,
  Building2,
  Car,
  CheckSquare,
  ClipboardList,
  Clock,
  FileText,
  Fingerprint,
  LogIn,
  Megaphone,
  Search,
  Shield,
  Truck,
  UserPlus,
  Users,
};

function label(item: HomeWidgetItem, lang: string): string {
  const l = item.label ?? {};
  return l[lang] || l.mr || l.en || item.key || "";
}

function CountTiles({ items, counts, lang }: { items: HomeWidgetItem[]; counts: Record<string, number>; lang: string }) {
  const router = useRouter();
  return (
    <View style={styles.tileRow}>
      {items.map((it, idx) => {
        const value = it.key ? counts[it.key] : undefined;
        const hot = (value ?? 0) > 0;
        return (
          <Pressable
            key={it.key ?? idx}
            testID={it.testID ?? `cfg-count-${it.key}`}
            accessibilityRole="button"
            disabled={!it.route}
            onPress={() => it.route && router.push(it.route as never)}
            style={({ pressed }) => [
              styles.countTile,
              shadow.card,
              hot && styles.countTileHot,
              { opacity: pressed ? 0.9 : 1 },
            ]}
          >
            <Text style={[styles.countValue, hot && styles.countValueHot]}>
              {value ?? "–"}
            </Text>
            <Text style={styles.countLabel} numberOfLines={2}>
              {it.emoji ? `${it.emoji} ` : ""}
              {label(it, lang)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function ActionGrid({ items, lang }: { items: HomeWidgetItem[]; lang: string }) {
  const router = useRouter();
  return (
    <View style={styles.gridWrap}>
      {items.map((it, idx) => {
        const Icon = ICONS[it.icon ?? ""] ?? ClipboardList;
        const tint = it.color || colors.primary;
        return (
          <Pressable
            key={it.route ?? idx}
            testID={it.testID ?? `cfg-action-${idx}`}
            accessibilityRole="button"
            onPress={() => it.route && router.push(it.route as never)}
            style={({ pressed }) => [
              styles.actionTile,
              shadow.card,
              idx === 0 && styles.actionPrimary,
              { opacity: pressed ? 0.9 : 1 },
            ]}
          >
            <View style={[styles.actionIconWrap, { backgroundColor: `${tint}18` }]}>
              {it.emoji ? (
                <Text style={styles.actionEmoji}>{it.emoji}</Text>
              ) : (
                <Icon size={30} color={tint} strokeWidth={2.2} />
              )}
            </View>
            <Text style={styles.actionLabel} numberOfLines={2}>
              {label(it, lang)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Renders a department/role home layout served by the backend. Widget types the
 * app doesn't know are silently skipped (forward compatibility: old APK + new
 * config never crashes). */
export function ConfigHome({
  widgets,
  counts,
}: {
  widgets: HomeWidget[];
  counts: Record<string, number> | null;
}) {
  const { i18n } = useTranslation();
  const lang = i18n.language || "mr";
  return (
    <View style={styles.wrap} testID="config-home">
      {widgets.map((w, i) => {
        if (w.type === "count_tiles" && w.items?.length) {
          return <CountTiles key={i} items={w.items} counts={counts ?? {}} lang={lang} />;
        }
        if (w.type === "action_grid" && w.items?.length) {
          return <ActionGrid key={i} items={w.items} lang={lang} />;
        }
        return null;
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.lg },
  tileRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  countTile: {
    flexGrow: 1,
    flexBasis: "30%",
    minHeight: 84,
    backgroundColor: "#FFFFFF",
    borderRadius: radius.lg,
    padding: spacing.md,
    justifyContent: "center",
    alignItems: "center",
    gap: 2,
  },
  countTileHot: { borderWidth: 2, borderColor: colors.warning },
  countValue: { fontFamily: fonts.bold, fontSize: 30, color: colors.text },
  countValueHot: { color: colors.warning },
  countLabel: {
    fontFamily: fonts.semiBold,
    fontSize: type.sm,
    color: colors.muted,
    textAlign: "center",
  },
  gridWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  actionTile: {
    flexGrow: 1,
    flexBasis: "45%",
    minHeight: 96,
    backgroundColor: "#FFFFFF",
    borderRadius: radius.lg,
    padding: spacing.md,
    justifyContent: "center",
    alignItems: "center",
    gap: spacing.xs,
  },
  actionPrimary: { flexBasis: "100%", minHeight: 104, borderWidth: 2, borderColor: colors.primary },
  actionIconWrap: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: "center",
    justifyContent: "center",
  },
  actionEmoji: { fontSize: 28 },
  actionLabel: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.text,
    textAlign: "center",
  },
});
