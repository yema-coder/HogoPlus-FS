import React, { useMemo, useState } from "react";
import { Image, StyleSheet, Text, View } from "react-native";

import { colors, radius } from "@/src/theme/tokens";

/** Small static map preview (OpenStreetMap tile + pin) — no API key needed.
 * The tile is positioned so the pin sits at the centre of the preview box. */
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
  const [failed, setFailed] = useState(false);
  const [width, setWidth] = useState(0);

  const tile = useMemo(() => {
    const n = 2 ** zoom;
    const xF = ((lng + 180) / 360) * n;
    const latR = (lat * Math.PI) / 180;
    const yF = ((1 - Math.log(Math.tan(latR) + 1 / Math.cos(latR)) / Math.PI) / 2) * n;
    const x = Math.floor(xF);
    const y = Math.floor(yF);
    return {
      url: `https://tile.openstreetmap.org/${zoom}/${x}/${y}.png`,
      px: (xF - x) * 256, // pin pixel offset inside the 256px tile
      py: (yF - y) * 256,
    };
  }, [lat, lng, zoom]);

  if (failed) return null;
  return (
    <View
      style={[styles.wrap, { height }]}
      testID={testID ?? "reg-map-preview"}
      onLayout={(e) => setWidth(e.nativeEvent.layout.width)}
    >
      {width > 0 ? (
        <>
          <Image
            source={{ uri: tile.url }}
            style={[
              styles.tile,
              { left: width / 2 - tile.px, top: height / 2 - tile.py },
            ]}
            onError={() => setFailed(true)}
          />
          <View style={[styles.pin, { left: width / 2 - 7, top: height / 2 - 14 }]} />
          <View style={[styles.pinDot, { left: width / 2 - 2, top: height / 2 - 2 }]} />
          <Text style={styles.attrib}>© OpenStreetMap</Text>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: "#e8e6df",
    borderWidth: 1,
    borderColor: colors.border,
  },
  tile: { position: "absolute", width: 256, height: 256 },
  pin: {
    position: "absolute",
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: "rgba(217,64,89,0.35)",
    borderWidth: 1.5,
    borderColor: "#d94059",
  },
  pinDot: {
    position: "absolute",
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: "#d94059",
  },
  attrib: {
    position: "absolute",
    right: 4,
    bottom: 2,
    fontSize: 8,
    color: "rgba(0,0,0,0.45)",
  },
});
