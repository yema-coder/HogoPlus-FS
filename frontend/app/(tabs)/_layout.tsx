import { Redirect, Tabs, usePathname, useRouter } from "expo-router";
import { Bell, ClipboardCheck, ClipboardList, Home, UserRound } from "lucide-react-native";
import React, { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { BackHandler, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { departmentIcon } from "@/src/constants/departments";
import { showToast } from "@/src/components/Toast";
import { useApprovalsStore } from "@/src/stores/approvalsStore";
import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { useNotifStore } from "@/src/stores/notifStore";
import { colors, fonts, sizes } from "@/src/theme/tokens";

/** Root tab paths — Android hardware back policy:
 *  sub-screen → pop (never exit; orphan deep-links land on home)
 *  non-home tab → go to home
 *  home → "press back again to exit" (2 s window) */
const ROOT_TAB_PATHS = ["/home", "/department", "/reports", "/approvals", "/alerts", "/profile"];

export default function TabsLayout() {
  const { t } = useTranslation();
  const insets = useSafeAreaInsets();
  const status = useAuthStore((s) => s.status);
  const profile = useAuthStore((s) => s.profile);
  const outboxCount = useOutboxStore((s) => s.items.length);
  const unread = useNotifStore((s) => s.unread);
  const approvalsTotal = useApprovalsStore((s) => s.total);
  const refreshApprovals = useApprovalsStore((s) => s.refresh);

  const rank = profile?.role?.rank ?? 6;
  const isManager = rank <= 3;
  const showAttendance = rank <= 2 || (profile?.department_code === "TIME_OFFICE" && rank === 3);
  const DeptIcon = departmentIcon(profile?.department_code ?? "");

  const router = useRouter();
  const pathname = usePathname();
  const pathRef = useRef(pathname);
  pathRef.current = pathname;
  const lastBackPress = useRef(0);

  useEffect(() => {
    if (Platform.OS !== "android") return;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      const p = pathRef.current;
      if (!ROOT_TAB_PATHS.includes(p)) {
        // a sub-screen is on top of the tabs — pop it; orphan deep-links go home
        if (router.canGoBack()) return false; // default pop
        router.replace("/(tabs)/home");
        return true;
      }
      if (p !== "/home") {
        router.navigate("/(tabs)/home");
        return true;
      }
      const now = Date.now();
      if (now - lastBackPress.current < 2000) return false; // second press → exit
      lastBackPress.current = now;
      showToast(t("common.pressAgainExit"));
      return true;
    });
    return () => sub.remove();
  }, [router, t]);

  useEffect(() => {
    if (isManager) void refreshApprovals(showAttendance);
  }, [isManager, showAttendance, refreshApprovals]);

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
        tabBarLabelStyle: { fontFamily: fonts.semiBold, fontSize: 11 },
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
        name="department"
        options={{
          title: t("tabs.dept"),
          tabBarIcon: ({ color }) => <DeptIcon size={26} color={color} strokeWidth={2.2} />,
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
        name="approvals"
        options={
          isManager
            ? {
                title: t("tabs.approvals"),
                tabBarBadge: approvalsTotal > 0 ? (approvalsTotal > 99 ? "99+" : approvalsTotal) : undefined,
                tabBarIcon: ({ color }) => <ClipboardCheck size={26} color={color} strokeWidth={2.2} />,
              }
            : { href: null }
        }
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
