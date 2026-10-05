// "Number plates" list for the incident detail screen. One row per detected
// plate (text + confidence + edited badge). When the viewer can edit, the row
// is tappable and shows a pencil → opens the plate editor in the parent screen.

import { Car, Pencil } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import type { DetectedPlate } from "@/src/api/types";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

export function PlateSection({
  plates,
  canEdit,
  onEdit,
  testID = "plate-section",
}: {
  plates: DetectedPlate[];
  canEdit: boolean;
  onEdit?: (p: DetectedPlate) => void;
  testID?: string;
}) {
  const { t } = useTranslation();
  if (plates.length === 0) return null;

  return (
    <View style={styles.wrap} testID={testID}>
      {plates.map((p) => {
        const conf = p.ocr_confidence ?? p.det_confidence;
        const inner = (
          <View style={styles.row}>
            <View style={styles.left}>
              <Car size={16} color={colors.accent} strokeWidth={2.4} />
              <Text style={styles.plate} numberOfLines={1}>
                {p.text || "?"}
              </Text>
            </View>
            <View style={styles.right}>
              {p.edited ? <Text style={styles.edited}>{t("incident.plateEdited")}</Text> : null}
              {conf != null ? <Text style={styles.conf}>{Math.round(conf * 100)}%</Text> : null}
              {canEdit ? <Pencil size={14} color={colors.primary} strokeWidth={2.4} /> : null}
            </View>
          </View>
        );
        return canEdit ? (
          <Pressable
            key={p.id}
            testID={`plate-row-${p.id}`}
            onPress={() => onEdit?.(p)}
            style={({ pressed }) => [styles.item, pressed && { opacity: 0.6 }]}
          >
            {inner}
          </Pressable>
        ) : (
          <View key={p.id} testID={`plate-row-${p.id}`} style={styles.item}>
            {inner}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  item: { paddingHorizontal: spacing.md, paddingVertical: spacing.md },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  left: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flex: 1 },
  right: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  plate: { fontFamily: fonts.bold, fontSize: type.base, color: colors.text, letterSpacing: 1.5 },
  conf: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  edited: {
    fontFamily: fonts.medium,
    fontSize: type.xs,
    color: colors.primary,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    paddingVertical: 2,
    overflow: "hidden",
  },
});
