import dayjs from "dayjs";
import { Play } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useAudioPlayer } from "expo-audio";
import { useTranslation } from "react-i18next";

import { fileUrl } from "@/src/api/client";
import { MediaCard } from "@/src/components/MediaCard";
import type { FormFieldDef } from "@/src/api/types";
import { tri } from "@/src/i18n";
import { prettyOption } from "@/src/forms/fields/SelectFieldInput";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

interface Props {
  field: FormFieldDef;
  value: unknown;
}

/** Read-only rendering of one submitted field (submission detail views). */
export function ReadOnlyField({ field, value }: Props) {
  const { t } = useTranslation();
  const player = useAudioPlayer();

  const body = () => {
    if (value === undefined || value === null || value === "") {
      return <Text style={styles.empty}>—</Text>;
    }
    switch (field.type) {
      case "photo":
        return (
          <MediaCard
            uri={fileUrl(String(value))}
            kind="photo"
            height={140}
            testID={`view-photo-${field.key}`}
          />
        );
      case "voice_note":
        return (
          <Pressable
            testID={`play-audio-${field.key}`}
            onPress={() => {
              player.replace({ uri: fileUrl(String(value)) });
              player.play();
            }}
            style={styles.playBtn}
          >
            <Play size={20} color={colors.onPrimary} strokeWidth={2.4} fill={colors.onPrimary} />
            <Text style={styles.playText}>{t("forms.play")}</Text>
          </Pressable>
        );
      case "gps_point": {
        const g = value as { lat?: number; lng?: number };
        return (
          <Text style={styles.value}>
            {typeof g.lat === "number" ? g.lat.toFixed(5) : "—"},{" "}
            {typeof g.lng === "number" ? g.lng.toFixed(5) : "—"}
          </Text>
        );
      }
      case "toggle":
        return <Text style={styles.value}>{value ? t("common.yes") : t("common.no")}</Text>;
      case "datetime":
        return <Text style={styles.value}>{dayjs(String(value)).format("DD/MM/YYYY HH:mm")}</Text>;
      case "select":
        return <Text style={styles.value}>{prettyOption(String(value))}</Text>;
      default:
        return <Text style={styles.value}>{String(value)}</Text>;
    }
  };

  return (
    <View style={styles.row} testID={`readonly-${field.key}`}>
      <Text style={styles.label}>{tri(field as unknown as Record<string, unknown>, "label")}</Text>
      {body()}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { gap: 4, paddingVertical: spacing.sm },
  label: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  value: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  empty: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted },
  thumb: {
    width: 140,
    height: 140,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  viewerBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.92)",
    alignItems: "center",
    justifyContent: "center",
  },
  viewerImage: { width: "100%", height: "80%" },
  playBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    minHeight: 48,
    alignSelf: "flex-start",
  },
  playText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.onPrimary },
});
