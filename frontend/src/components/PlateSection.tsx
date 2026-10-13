// "Number plates" list for the incident detail screen. One row per detected
// plate: a client-side CROP of the plate from the photo + the read, a PRIMARY
// badge (the authoritative detected_plate), a confidence TIER (colour + dot +
// text, never colour alone), an edited badge, and — when corrected — the model's
// ORIGINAL read beside it. When the viewer can edit, the row opens the editor.

import { CheckCircle2, Pencil } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import type { DetectedPlate } from "@/src/api/types";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

const CROP_W = 96;
const CROP_H = 58;
const PAD = 1.3; // zoom-out so the whole plate fits comfortably in the crop

function tierOf(conf: number | null): { key: "high" | "medium" | "low"; color: string } {
  const c = conf ?? 0;
  if (c >= 0.85) return { key: "high", color: colors.success };
  if (c >= 0.6) return { key: "medium", color: colors.warning };
  return { key: "low", color: colors.danger };
}

function PlateCrop({
  photoUrl,
  plate,
  dims,
}: {
  photoUrl: string;
  plate: DetectedPlate;
  dims: { w: number; h: number } | null;
}) {
  if (!dims) return <View style={styles.crop} />;
  const pw = plate.w * dims.w;
  const ph = plate.h * dims.h;
  const scale = Math.min(CROP_W / (pw * PAD || 1), CROP_H / (ph * PAD || 1));
  const renderW = dims.w * scale;
  const renderH = dims.h * scale;
  const left = CROP_W / 2 - (plate.x * dims.w + pw / 2) * scale;
  const top = CROP_H / 2 - (plate.y * dims.h + ph / 2) * scale;
  return (
    <View style={styles.crop}>
      <Image
        source={{ uri: photoUrl }}
        style={{ position: "absolute", width: renderW, height: renderH, left, top }}
        resizeMode="cover"
      />
    </View>
  );
}

export function PlateSection({
  plates,
  photoUrl,
  primaryText,
  canEdit,
  onEdit,
  testID = "plate-section",
}: {
  plates: DetectedPlate[];
  photoUrl: string;
  primaryText?: string | null;
  canEdit: boolean;
  onEdit?: (p: DetectedPlate) => void;
  testID?: string;
}) {
  const { t } = useTranslation();
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    let alive = true;
    Image.getSize(
      photoUrl,
      (w, h) => alive && w && h && setDims({ w, h }),
      () => alive && setDims(null),
    );
    return () => {
      alive = false;
    };
  }, [photoUrl]);

  if (plates.length === 0) return null;

  return (
    <View style={styles.wrap} testID={testID}>
      {plates.map((p) => {
        const conf = p.ocr_confidence ?? p.det_confidence;
        const tr = tierOf(conf);
        const isPrimary =
          !!primaryText && (p.text ?? "").toUpperCase() === primaryText.toUpperCase();
        const showOriginal =
          p.edited &&
          !!p.original_text &&
          p.original_text.toUpperCase() !== (p.text ?? "").toUpperCase();
        const inner = (
          <View style={styles.rowWrap}>
            <PlateCrop photoUrl={photoUrl} plate={p} dims={dims} />
            <View style={styles.info}>
              <View style={styles.topRow}>
                <Text style={styles.plate} numberOfLines={1}>
                  {p.text || "?"}
                </Text>
                {isPrimary ? (
                  <View style={styles.primaryBadge} testID="plate-primary-badge">
                    <CheckCircle2 size={12} color={colors.onPrimary} strokeWidth={2.6} />
                    <Text style={styles.primaryText}>{t("incident.platePrimary")}</Text>
                  </View>
                ) : null}
              </View>
              <View style={styles.metaRow}>
                <View style={[styles.tierChip, { backgroundColor: `${tr.color}1A`, borderColor: tr.color }]}>
                  <View style={[styles.tierDot, { backgroundColor: tr.color }]} />
                  <Text style={[styles.tierText, { color: tr.color }]}>
                    {t(`incident.conf_${tr.key}`)}
                    {conf != null ? ` · ${Math.round(conf * 100)}%` : ""}
                  </Text>
                </View>
                {p.edited ? <Text style={styles.edited}>{t("incident.plateEdited")}</Text> : null}
                {canEdit ? <Pencil size={14} color={colors.primary} strokeWidth={2.4} /> : null}
              </View>
              {showOriginal ? (
                <Text style={styles.original} numberOfLines={1}>
                  {t("incident.plateModelRead", { v: p.original_text })}
                </Text>
              ) : null}
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
  rowWrap: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  crop: {
    width: CROP_W,
    height: CROP_H,
    borderRadius: radius.sm,
    overflow: "hidden",
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  info: { flex: 1, gap: 4 },
  topRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  plate: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, letterSpacing: 1.5, flexShrink: 1 },
  primaryBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: colors.primary,
    borderRadius: radius.pill,
    paddingHorizontal: 7,
    paddingVertical: 2,
  },
  primaryText: { fontFamily: fonts.bold, fontSize: type.xs, color: colors.onPrimary },
  metaRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  tierChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    borderRadius: radius.pill,
    borderWidth: 1,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  tierDot: { width: 7, height: 7, borderRadius: 4 },
  tierText: { fontFamily: fonts.semiBold, fontSize: type.xs },
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
  original: { fontFamily: fonts.regular, fontSize: type.xs, color: colors.muted, fontStyle: "italic" },
});
