import { AlertTriangle, CheckCircle2, Info } from "lucide-react-native";
import React, { useEffect } from "react";
import { StyleSheet, Text, View } from "react-native";
import Animated, { FadeInUp, FadeOutUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { create } from "zustand";

import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

type ToastType = "success" | "error" | "info";

interface ToastState {
  message: string | null;
  toastType: ToastType;
  show: (message: string, toastType?: ToastType) => void;
  hide: () => void;
}

export const useToastStore = create<ToastState>((set) => ({
  message: null,
  toastType: "info",
  show: (message, toastType = "info") => set({ message, toastType }),
  hide: () => set({ message: null }),
}));

export function showToast(message: string, toastType: ToastType = "info"): void {
  useToastStore.getState().show(message, toastType);
}

const TINT: Record<ToastType, string> = {
  success: colors.success,
  error: colors.danger,
  info: colors.primary,
};

export function ToastHost() {
  const { message, toastType, hide } = useToastStore();
  const insets = useSafeAreaInsets();

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(hide, 3200);
    return () => clearTimeout(timer);
  }, [message, hide]);

  if (!message) return null;
  const Icon = toastType === "success" ? CheckCircle2 : toastType === "error" ? AlertTriangle : Info;

  return (
    <View pointerEvents="none" style={[styles.host, { top: insets.top + spacing.sm }]}>
      <Animated.View entering={FadeInUp.duration(200)} exiting={FadeOutUp.duration(150)}>
        <View style={[styles.toast, { backgroundColor: TINT[toastType] }]} testID="toast">
          <Icon size={22} color="#FFFFFF" strokeWidth={2.4} />
          <Text style={styles.text} numberOfLines={2} testID="toast-message">
            {message}
          </Text>
        </View>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  host: {
    position: "absolute",
    left: spacing.lg,
    right: spacing.lg,
    alignItems: "center",
  },
  toast: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    maxWidth: 480,
  },
  text: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: "#FFFFFF",
    flexShrink: 1,
  },
});
