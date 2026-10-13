import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Image, Linking, Platform, Pressable, StyleSheet, Text, View } from "react-native";

import { fetchMapImageUri } from "@/src/api/client";
import { colors, radius } from "@/src/theme/tokens";

/** Static map preview backed by Mappls (MapmyIndia), proxied through the backend so the
 * Mappls token never reaches the device. On ANY failure it falls back to the raw
 * coordinates + an "Open in Maps" button (Mappls web) — never a broken tile, never OSM. */
export function MapPreview({
  lat,
  lng,
  zoom = 16,
  height = 130,
  testID,
}: {
  lat: number;
  lng: number;
  zoom?: number;
  height?: number;
  testID?: string;
}) {
  const { t } = useTranslation();
  const [uri, setUri] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setUri(null);
    setFailed(false);
    fetchMapImageUri(lat, lng, zoom)
      .then((u) => {
        if (!active) return;
        if (u) setUri(u);
        else setFailed(true);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [lat, lng, zoom]);

  const openExternal = () =>
    Linking.openURL(`https://maps.mappls.com/@${lat},${lng},17z`).catch(() => undefined);

  if (failed) {
    return (
      <View style={[styles.fallback, { minHeight: height }]} testID={testID ?? "reg-map-preview"}>
        <Text style={styles.coords}>
          {lat.toFixed(5)}, {lng.toFixed(5)}
        </Text>
        <Pressable
          accessibilityRole="button"
          onPress={openExternal}
          style={({ pressed }) => [styles.openBtn, pressed && { opacity: 0.7 }]}
          testID="map-open-external"
        >
          <Text style={styles.openBtnText}>{t("incident.openInMaps")}</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={[styles.wrap, { height }]} testID={testID ?? "reg-map-preview"}>
      {uri ? (
        <Pressable style={styles.fill} onPress={openExternal} accessibilityRole="imagebutton">
          <Image
            source={{ uri }}
            style={styles.fill}
            resizeMode="cover"
            onError={() => setFailed(true)}
          />
          <Text style={styles.attrib}>© Mappls</Text>
        </Pressable>
      ) : (
        <View style={styles.fill} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  fill: { flex: 1, width: "100%", height: "100%" },
  attrib: {
    position: "absolute",
    right: 4,
    bottom: 2,
    fontSize: 8,
    color: "rgba(0,0,0,0.45)",
  },
  fallback: {
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    padding: 12,
  },
  coords: {
    fontFamily: Platform.select({ ios: "Courier", android: "monospace", default: "monospace" }),
    fontSize: 12,
    color: colors.muted,
  },
  openBtn: {
    backgroundColor: colors.brandTertiary,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
  },
  openBtnText: { color: colors.primary, fontWeight: "600", fontSize: 13 },
});
