// Horizontal strip of CLEAR (un-blurred) square face crops derived client-side
// from the incident photo. Each crop uniformly scales + centres the detected
// face bbox inside a fixed square (no distortion). Tap → opens the boxes viewer.

import React, { useEffect, useState } from "react";
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { DetectedFace } from "@/src/api/types";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

const THUMB = 76;
const PAD = 1.18; // zoom-out so the whole face comfortably fits the thumbnail

export function FaceStrip({
  photoUrl,
  faces,
  onPress,
  testID = "face-strip",
}: {
  photoUrl: string;
  faces: DetectedFace[];
  onPress?: () => void;
  testID?: string;
}) {
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    let alive = true;
    Image.getSize(
      photoUrl,
      (w, h) => {
        if (alive && w && h) setDims({ w, h });
      },
      () => {
        if (alive) setDims(null);
      },
    );
    return () => {
      alive = false;
    };
  }, [photoUrl]);

  if (faces.length === 0) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      testID={testID}
    >
      {faces.map((f, i) => (
        <Pressable
          key={f.id}
          onPress={onPress}
          style={styles.crop}
          testID={`face-crop-${f.id}`}
          accessibilityRole="imagebutton"
        >
          <FaceCrop photoUrl={photoUrl} face={f} dims={dims} />
          <Text style={styles.idx} numberOfLines={1}>
            #{i + 1}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

function FaceCrop({
  photoUrl,
  face,
  dims,
}: {
  photoUrl: string;
  face: DetectedFace;
  dims: { w: number; h: number } | null;
}) {
  if (!dims) return <View style={styles.thumb} />;

  const fw = face.w * dims.w;
  const fh = face.h * dims.h;
  const scale = THUMB / (Math.max(fw, fh, 1) * PAD);
  const renderW = dims.w * scale;
  const renderH = dims.h * scale;
  const left = THUMB / 2 - (face.x * dims.w + fw / 2) * scale;
  const top = THUMB / 2 - (face.y * dims.h + fh / 2) * scale;

  return (
    <View style={styles.thumb}>
      <Image
        source={{ uri: photoUrl }}
        style={{ position: "absolute", width: renderW, height: renderH, left, top }}
        resizeMode="cover"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { gap: spacing.sm, paddingVertical: spacing.xs },
  crop: { alignItems: "center", gap: 3 },
  thumb: {
    width: THUMB,
    height: THUMB,
    borderRadius: radius.sm,
    overflow: "hidden",
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  idx: { fontFamily: fonts.medium, fontSize: type.xs, color: colors.muted },
});
