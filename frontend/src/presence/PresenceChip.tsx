import { useFocusEffect, useRouter } from "expo-router";
import * as Location from "expo-location";
import { MapPin, MapPinOff, SatelliteDish } from "lucide-react-native";
import React, { useCallback, useState } from "react";
import { Platform, Pressable, StyleSheet, Text } from "react-native";
import { useTranslation } from "react-i18next";

import { presenceMyStatus, type PresenceMyStatus } from "@/src/api/endpoints";
import { isTrackingActive, resumeIfNeeded, startTracking } from "@/src/presence/tracker";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

/** Worker-home presence chip: shows the honest tracking state during a shift,
 * asks for consent when needed and nudges (in the user's language, Marathi
 * default) when GPS is off. Renders nothing for non-pilot workers. */
export function PresenceChip({ punchedIn }: { punchedIn: boolean }) {
  const router = useRouter();
  const { t } = useTranslation();
  const [status, setStatus] = useState<PresenceMyStatus | null>(null);
  const [active, setActive] = useState(false);
  const [gpsOn, setGpsOn] = useState(true);

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      void (async () => {
        try {
          const s = await presenceMyStatus();
          if (!alive) return;
          setStatus(s);
          if (s.enabled && s.in_pilot) {
            await resumeIfNeeded();
            if (!alive) return;
            setActive(await isTrackingActive());
            if (Platform.OS !== "web") {
              try {
                setGpsOn(await Location.hasServicesEnabledAsync());
              } catch {
                setGpsOn(true);
              }
            }
          }
        } catch {
          // offline — keep last known chip state
        }
      })();
      return () => {
        alive = false;
      };
    }, []),
  );

  if (!status || !status.enabled || !status.in_pilot) return null;

  if (status.consent_required && punchedIn) {
    return (
      <Pressable
        testID="presence-chip-consent"
        style={[styles.chip, styles.blue]}
        onPress={() => router.push("/presence-consent")}
      >
        <MapPin size={16} color={colors.accent} strokeWidth={2.4} />
        <Text style={[styles.text, { color: colors.accent }]}>{t("presence.consentCta")}</Text>
      </Pressable>
    );
  }
  if (!status.tracking_expected) return null;

  if (active && !gpsOn) {
    return (
      <Pressable
        testID="presence-chip-gps-off"
        style={[styles.chip, styles.amber]}
        onPress={() => router.push("/battery-help")}
      >
        <SatelliteDish size={16} color={"#B26A00"} strokeWidth={2.4} />
        <Text style={[styles.text, { color: "#B26A00" }]}>{t("presence.gpsOff")}</Text>
      </Pressable>
    );
  }
  if (active) {
    return (
      <Pressable
        testID="presence-chip-on"
        style={[styles.chip, styles.green]}
        onPress={() => router.push("/battery-help")}
      >
        <MapPin size={16} color={colors.success} strokeWidth={2.4} />
        <Text style={[styles.text, { color: "#15803D" }]}>{t("presence.chipOn")}</Text>
      </Pressable>
    );
  }
  return (
    <Pressable
      testID="presence-chip-off"
      style={[styles.chip, styles.amber]}
      onPress={() =>
        void startTracking().then((ok) => {
          setActive(ok);
          if (!ok) router.push("/battery-help");
        })
      }
    >
      <MapPinOff size={16} color={"#B26A00"} strokeWidth={2.4} />
      <Text style={[styles.text, { color: "#B26A00" }]}>{t("presence.chipOff")}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    alignSelf: "flex-start",
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderRadius: radius.pill,
    marginTop: spacing.sm,
    minHeight: 36,
  },
  green: { backgroundColor: "#E4F4E8" },
  amber: { backgroundColor: "#FCEEDB" },
  blue: { backgroundColor: "#E3EAF8" },
  text: { fontFamily: fonts.bold, fontSize: type.sm },
});
