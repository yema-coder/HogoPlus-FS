import { Redirect, Tabs } from "expo-router";
import { Bell, ClipboardList, Home, UserRound } from "lucide-react-native";
import React from "react";
import { useTranslation } from "react-i18next";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { useNotifStore } from "@/src/stores/notifStore";
import { colors, fonts, sizes } from "@/src/theme/tokens";

export default function TabsLayout() {
  const { t } = useTranslation();
  const insets = useSafeAreaInsets();
  const status = useAuthStore((s) => s.status);
  const profile = useAuthStore((s) => s.profile);
  const outboxCount = useOutboxStore((s) => s.items.length);
  const unread = useNotifStore((s) => s.unread);

  if (status === "loading") return null;
  if (status === "unauthenticated") return <Redirect href="/(auth)/phone" />;
  if (profile && profile.onboarding_status !== "approved") return <Redirect href="/(auth)/pending" />;

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          height: sizes.bottomTabHeight + insets.bottom,
          paddingTop: 8,
          paddingBottom: Math.max(insets.bottom, 10),
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
        },
        tabBarLabelStyle: { fontFamily: fonts.semiBold, fontSize: 13 },
        tabBarBadgeStyle: {
          backgroundColor: colors.danger,
          color: "#FFFFFF",
          fontFamily: fonts.bold,
          fontSize: 11,
        },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{
          title: t("tabs.home"),
          tabBarIcon: ({ color }) => <Home size={26} color={color} strokeWidth={2.2} />,
        }}
      />
      <Tabs.Screen
        name="reports"
        options={{
          title: t("tabs.reports"),
          tabBarBadge: outboxCount > 0 ? outboxCount : undefined,
          tabBarIcon: ({ color }) => <ClipboardList size={26} color={color} strokeWidth={2.2} />,
        }}
      />
      <Tabs.Screen
        name="alerts"
        options={{
          title: t("tabs.alerts"),
          tabBarBadge: unread > 0 ? (unread > 99 ? "99+" : unread) : undefined,
          tabBarIcon: ({ color }) => <Bell size={26} color={color} strokeWidth={2.2} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: t("tabs.profile"),
          tabBarIcon: ({ color }) => <UserRound size={26} color={color} strokeWidth={2.2} />,
        }}
      />
    </Tabs>
  );
}
