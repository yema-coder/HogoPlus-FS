import { Platform } from "react-native";

export const colors = {
  primary: "#0B4F6C",
  accent: "#3A5DAE",
  success: "#22C55E",
  danger: "#E85A6F",
  warning: "#F59E0B",
  background: "#F9F8F5",
  surface: "#FFFFFF",
  surfaceTertiary: "#E8E6E1",
  border: "#D4D1CA",
  borderStrong: "#A3A099",
  text: "#28251D",
  muted: "#7A7974",
  onPrimary: "#F9F8F5",
  onDanger: "#FFFFFF",
  onSuccess: "#FFFFFF",
  onWarning: "#28251D",
  brandTertiary: "#DCE6F0",
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

export const radius = {
  sm: 8,
  md: 16,
  lg: 24,
  pill: 999,
} as const;

export const sizes = {
  screenPadding: 16,
  headerHeight: 72,
  bottomTabHeight: 72,
  touchTarget: 56,
  incidentTile: 120,
  categoryCircle: 110,
  fab: 56,
  cameraShutter: 88,
} as const;

export const fonts = {
  regular: "Baloo2-Regular",
  medium: "Baloo2-Medium",
  semiBold: "Baloo2-SemiBold",
  bold: "Baloo2-Bold",
} as const;

export const type = {
  sm: 14,
  base: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
} as const;

export const shadow = {
  card: Platform.select({
    web: { boxShadow: "0px 2px 6px rgba(40, 37, 29, 0.08)" },
    default: {
      shadowColor: "#28251D",
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.08,
      shadowRadius: 6,
      elevation: 2,
    },
  }) as object,
} as const;

export const statusColors: Record<string, string> = {
  submitted: colors.accent,
  seen: colors.primary,
  in_progress: colors.warning,
  resolved: colors.success,
  escalated: colors.danger,
  queued: colors.warning,
  approved: colors.success,
  rejected: colors.danger,
};
