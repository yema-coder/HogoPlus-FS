import {
  Building2,
  Calculator,
  Clock,
  Factory,
  FlaskConical,
  Hammer,
  Package,
  Shield,
  ShoppingCart,
  Sprout,
  Truck,
  Warehouse,
  Wrench,
  type LucideIcon,
} from "lucide-react-native";

export const DEPARTMENT_ICONS: Record<string, LucideIcon> = {
  ACCOUNTS: Calculator,
  ADMIN: Building2,
  AGRICULTURE: Sprout,
  CANE_YARD: Truck,
  CIVIL: Hammer,
  DISTILLERY: FlaskConical,
  ENGINEERING: Wrench,
  GODOWN: Warehouse,
  PRODUCTION: Factory,
  PURCHASE: ShoppingCart,
  SECURITY: Shield,
  STORE: Package,
  TIME_OFFICE: Clock,
};

export function departmentIcon(code: string): LucideIcon {
  return DEPARTMENT_ICONS[code] ?? Building2;
}
