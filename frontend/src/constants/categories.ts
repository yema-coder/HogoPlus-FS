import {
  Bandage,
  Cog,
  Droplets,
  Flame,
  HardHat,
  MoreHorizontal,
  Shield,
  Zap,
  type LucideIcon,
} from "lucide-react-native";

import type { IncidentCategory } from "@/src/api/types";
import { colors } from "@/src/theme/tokens";

export interface CategoryDef {
  code: IncidentCategory;
  tKey: string; // cat.*
  icon: LucideIcon;
  tint: string;
}

export const INCIDENT_CATEGORIES: CategoryDef[] = [
  { code: "safety", tKey: "cat.safety", icon: HardHat, tint: colors.warning },
  { code: "fire", tKey: "cat.fire", icon: Flame, tint: colors.danger },
  { code: "machine_breakdown", tKey: "cat.machine", icon: Cog, tint: colors.primary },
  { code: "injury", tKey: "cat.injury", icon: Bandage, tint: colors.danger },
  { code: "electrical", tKey: "cat.electrical", icon: Zap, tint: colors.warning },
  { code: "water_leakage", tKey: "cat.water", icon: Droplets, tint: colors.accent },
  { code: "security", tKey: "cat.security", icon: Shield, tint: colors.primary },
  { code: "other", tKey: "cat.other", icon: MoreHorizontal, tint: colors.muted },
];

export function categoryDef(code: string): CategoryDef {
  return INCIDENT_CATEGORIES.find((c) => c.code === code) ?? INCIDENT_CATEGORIES[7];
}
