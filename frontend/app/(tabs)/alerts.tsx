import { useFocusEffect, useRouter } from "expo-router";
import { Bell } from "lucide-react-native";
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { markNotificationRead, myNotifications } from "@/src/api/endpoints";
import type { NotificationItem, NotificationList } from "@/src/api/types";
import { EmptyState } from "@/src/components/EmptyState";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { SpeakerButton } from "@/src/components/SpeakerButton";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { useNotifStore } from "@/src/stores/notifStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { timeAgo } from "@/src/utils/format";

export default function AlertsScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const rank = useAuthStore((s) => s.profile?.role?.rank ?? 6);
  const { data, loading, error, refresh } = useCachedFetch<NotificationList>(
    "notifs",
    myNotifications,
  );
  const setUnread = useNotifStore((s) => s.setUnread);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (data) {
      const unread = data.items.filter((n) => !n.is_read && !readIds.has(n.id)).length;
      setUnread(unread);
    }
  }, [data, readIds, setUnread]);

  useFocusEffect(
    useCallback(() => {
      void refresh();
    }, [refresh]),
  );

  const open = (item: NotificationItem) => {
    const isRead = item.is_read || readIds.has(item.id);
    if (!isRead) {
      setReadIds((prev) => new Set(prev).add(item.id));
      markNotificationRead(item.id).catch(() => undefined);
    }
    if (item.entity_type === "incident" && item.entity_id) {
      router.push({ pathname: "/incident/[id]", params: { id: item.entity_id } });
    } else if (item.entity_type === "form_submission" && item.entity_id) {
      router.push({ pathname: "/submission/[id]", params: { id: item.entity_id } });
    } else if (item.entity_type === "shift_swap") {
      router.push("/shift");
    } else if (item.entity_type === "employee") {
      if (rank <= 3) router.push("/(tabs)/approvals");
    } else if (item.entity_type === "attendance") {
      router.push("/attendance/history");
    } else if (item.entity_type === "vehicle") {
      router.push("/vehicle");
    }
  };

  const renderRow = ({ item }: { item: NotificationItem }) => {
    const isRead = item.is_read || readIds.has(item.id);
    return (
      <Pressable
        testID={`notification-row-${item.id}`}
        accessibilityRole="button"
        onPress={() => open(item)}
        style={({ pressed }) => [
          styles.row,
          !isRead && styles.rowUnread,
          { opacity: pressed ? 0.85 : 1 },
        ]}
      >
        {!isRead ? <View style={styles.dot} testID={`notification-unread-dot-${item.id}`} /> : <View style={styles.dotSpace} />}
        <View style={styles.body}>
          <Text style={[styles.title, !isRead && styles.titleUnread]} numberOfLines={1}>
            {tri(item as unknown as Record<string, unknown>, "title")}
          </Text>
          <Text style={styles.text} numberOfLines={2}>
            {tri(item as unknown as Record<string, unknown>, "body")}
          </Text>
          <Text style={styles.time}>{timeAgo(item.created_at)}</Text>
        </View>
        <SpeakerButton
          text={`${tri(item as unknown as Record<string, unknown>, "title")}. ${tri(item as unknown as Record<string, unknown>, "body")}`}
          testID={`notification-tts-${item.id}`}
        />
      </Pressable>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={[]} testID="alerts-screen">
      <ScreenHeader title={t("notif.title")} back={false} />
      {error && !data ? (
        <ErrorRetry onRetry={() => void refresh()} />
      ) : (
        <FlatList
          data={data?.items ?? []}
          keyExtractor={(n) => n.id}
          renderItem={renderRow}
          contentContainerStyle={styles.list}
          refreshing={loading}
          onRefresh={() => void refresh()}
          ListEmptyComponent={<EmptyState icon={Bell} title={t("notif.empty")} />}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  list: { padding: sizes.screenPadding, gap: spacing.md, flexGrow: 1 },
  row: {
    flexDirection: "row",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  rowUnread: { borderColor: colors.primary, borderWidth: 2 },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.danger,
    marginTop: 8,
  },
  dotSpace: { width: 10 },
  body: { flex: 1, gap: 2 },
  title: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  titleUnread: { fontFamily: fonts.bold },
  text: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  time: { fontFamily: fonts.regular, fontSize: 12, color: colors.muted, marginTop: 2 },
});
