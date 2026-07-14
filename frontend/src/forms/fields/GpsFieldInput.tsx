import { MapPin, MapPinCheck, Settings } from "lucide-react-native";
import React, { useState } from "react";
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { showToast } from "@/src/components/Toast";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { acquireGps } from "@/src/utils/gps";

export interface GpsValue {
  lat: number;
  lng: number;
  accuracy?: number | null;
}

interface Props {
  value: GpsValue | undefined;
  onChange: (v: GpsValue) => void;
  error?: boolean;
  testID: string;
}

export function GpsFieldInput({ value, onChange, error, testID }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);

  const capture = async () => {
    setBusy(true);
    const res = await acquireGps(10000);
    setBusy(false);
    if (res.fix) {
      setBlocked(false);
      onChange({ lat: res.fix.lat, lng: res.fix.lng, accuracy: res.fix.accuracy });
    } else if (res.blocked) {
      setBlocked(true);
    } else {
      showToast(t("incident.gpsNone"), "error");
    }
  };

  return (
    <View style={styles.wrap}>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        onPress={() => void capture()}
        style={[styles.row, value && styles.rowDone, error && !value && styles.rowError]}
      >
        {busy ? (
          <ActivityIndicator size="small" color={colors.primary} />
        ) : value ? (
          <MapPinCheck size={24} color={colors.success} strokeWidth={2.2} />
        ) : (
          <MapPin size={24} color={colors.muted} strokeWidth={2.2} />
        )}
        <Text style={[styles.rowText, !value && { color: colors.muted }]}>
          {value
            ? t("forms.locationCaptured", { m: Math.round(value.accuracy ?? 0) })
            : t("forms.captureLocation")}
        </Text>
      </Pressable>
      {value ? (
        <Text style={styles.coords}>
          {value.lat.toFixed(5)}, {value.lng.toFixed(5)}
        </Text>
      ) : null}
      {blocked ? (
        <Pressable
          testID={`${testID}-settings`}
          onPress={() => void Linking.openSettings()}
          style={styles.settingsBtn}
        >
          <Settings size={18} color={colors.accent} strokeWidth={2.2} />
          <Text style={styles.settingsText}>{t("common.openSettings")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  row: {
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
  },
  rowDone: { borderColor: colors.success },
  rowError: { borderColor: colors.danger },
  rowText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text, flexShrink: 1 },
  coords: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted },
  settingsBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 44,
  },
  settingsText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.accent },
});
