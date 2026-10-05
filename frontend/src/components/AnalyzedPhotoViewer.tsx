// Full-screen photo viewer that overlays the detection boxes (faces + plates)
// on the un-cropped image. The image is laid out at its own aspect ratio so the
// normalized boxes line up exactly; pinch-zoom via the enclosing ScrollView.

import { X } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import {
  Dimensions,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useTranslation } from "react-i18next";

import type { DetectedFace, DetectedPlate } from "@/src/api/types";
import { colors, fonts, radius } from "@/src/theme/tokens";

type Box = { x: number; y: number; w: number; h: number };

function pct(b: Box) {
  return {
    left: `${b.x * 100}%`,
    top: `${b.y * 100}%`,
    width: `${b.w * 100}%`,
    height: `${b.h * 100}%`,
  } as const;
}

export function AnalyzedPhotoViewer({
  uri,
  faces,
  plates,
  onClose,
}: {
  uri: string | null;
  faces: DetectedFace[];
  plates: DetectedPlate[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [aspect, setAspect] = useState(3 / 4);

  useEffect(() => {
    if (!uri) return;
    let alive = true;
    Image.getSize(
      uri,
      (w, h) => {
        if (alive && w && h) setAspect(w / h);
      },
      () => {},
    );
    return () => {
      alive = false;
    };
  }, [uri]);

  const screen = Dimensions.get("window");
  let imgW = screen.width;
  let imgH = imgW / aspect;
  if (imgH > screen.height * 0.82) {
    imgH = screen.height * 0.82;
    imgW = imgH * aspect;
  }

  return (
    <Modal visible={!!uri} animationType="fade" onRequestClose={onClose}>
      <View style={styles.wrap} testID="analyzed-photo-viewer">
        {uri ? (
          <ScrollView
            style={{ flex: 1 }}
            contentContainerStyle={styles.content}
            maximumZoomScale={4}
            minimumZoomScale={1}
            centerContent
          >
            <View style={{ width: imgW, height: imgH }}>
              <Image source={{ uri }} style={{ width: imgW, height: imgH }} resizeMode="contain" />
              {plates.map((p) => (
                <View key={p.id} style={[styles.box, styles.plateBox, pct(p)]}>
                  <View style={styles.plateTag}>
                    <Text style={styles.plateTagText} numberOfLines={1}>
                      {p.text || "?"}
                    </Text>
                  </View>
                </View>
              ))}
              {faces.map((f, i) => (
                <View key={f.id} style={[styles.box, styles.faceBox, pct(f)]}>
                  <View style={styles.faceTag}>
                    <Text style={styles.faceTagText}>#{i + 1}</Text>
                  </View>
                </View>
              ))}
            </View>
          </ScrollView>
        ) : null}
        <Pressable
          onPress={onClose}
          style={styles.closeBtn}
          testID="analyzed-viewer-close"
          accessibilityRole="button"
          accessibilityLabel={t("media.close")}
        >
          <X size={26} color="#FFFFFF" strokeWidth={2.5} />
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: "#000000" },
  content: { flexGrow: 1, alignItems: "center", justifyContent: "center" },
  box: { position: "absolute" },
  plateBox: { borderWidth: 2.5, borderColor: colors.accent, borderRadius: 4 },
  plateTag: {
    position: "absolute",
    top: -22,
    left: -2,
    backgroundColor: colors.accent,
    borderRadius: radius.sm,
    paddingHorizontal: 6,
    paddingVertical: 2,
    maxWidth: 160,
  },
  plateTagText: { fontFamily: fonts.bold, fontSize: 11, color: "#FFFFFF" },
  faceBox: { borderWidth: 2, borderColor: colors.warning, borderRadius: 6 },
  faceTag: {
    position: "absolute",
    top: -18,
    left: -2,
    backgroundColor: colors.warning,
    borderRadius: radius.sm,
    paddingHorizontal: 5,
    paddingVertical: 1,
  },
  faceTagText: { fontFamily: fonts.bold, fontSize: 10, color: "#28251D" },
  closeBtn: {
    position: "absolute",
    top: 48,
    right: 20,
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
  },
});
