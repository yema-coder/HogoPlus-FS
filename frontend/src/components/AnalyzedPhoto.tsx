// Step 4 — the analysed incident photo: faces + number plates drawn as boxes on
// the image. Plate boxes are tappable (→ edit). A "Blur faces" toggle privacy-
// masks every detected face, and "Share" exports the photo with faces ALWAYS
// redacted (opaque patches burned in via view-shot) so a shared report never
// leaks a face — regardless of the on-screen toggle.

import * as Sharing from "expo-sharing";
import { EyeOff, Maximize2, Pencil, Share2 } from "lucide-react-native";
import React, { useRef, useState } from "react";
import {
  Image,
  LayoutChangeEvent,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import ViewShot, { captureRef } from "react-native-view-shot";
import { useTranslation } from "react-i18next";

import type { DetectedFace, DetectedPlate } from "@/src/api/types";
import { MediaViewerModal } from "@/src/components/MediaCard";
import { showToast } from "@/src/components/Toast";
import { colors, fonts, radius, type } from "@/src/theme/tokens";

const LOGO = require("@/assets/images/logo.png");
const CAPTURE_WIDTH = 1080; // px of the exported (redacted) image

interface Props {
  photoUrl: string;
  faces: DetectedFace[];
  plates: DetectedPlate[];
  onPlatePress?: (plate: DetectedPlate) => void;
  testID?: string;
}

function FaceMask({ face, box }: { face: DetectedFace; box: boolean }) {
  // opaque frosted patch that fully hides the face (privacy-safe); `box` adds a
  // thin outline used in the on-screen preview only
  return (
    <View
      pointerEvents="none"
      style={[
        styles.abs,
        {
          left: `${face.x * 100}%`,
          top: `${face.y * 100}%`,
          width: `${face.w * 100}%`,
          height: `${face.h * 100}%`,
        },
        styles.faceMask,
        box && styles.faceMaskOutline,
      ]}
    >
      <View style={styles.faceMaskInner} />
    </View>
  );
}

export function AnalyzedPhoto({ photoUrl, faces, plates, onPlatePress, testID = "analyzed-photo" }: Props) {
  const { t } = useTranslation();
  const [w, setW] = useState(0);
  const [aspect, setAspect] = useState(3 / 4); // w/h until the image reports its size
  const [blur, setBlur] = useState(false);
  const [viewer, setViewer] = useState(false);
  const [sharing, setSharing] = useState(false);
  const shotRef = useRef<View>(null);

  const h = w ? w / aspect : 220;
  const hasFaces = faces.length > 0;

  const onLayout = (e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width);
  const onImgLoad = (e: { nativeEvent: { source?: { width: number; height: number } } }) => {
    const s = e.nativeEvent.source;
    if (s && s.width && s.height) setAspect(s.width / s.height);
  };

  const share = async () => {
    if (sharing) return;
    setSharing(true);
    try {
      const uri = await captureRef(shotRef, { format: "jpg", quality: 0.9 });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(uri, { mimeType: "image/jpeg", dialogTitle: t("incident.share") });
        if (hasFaces) showToast(t("incident.facesHiddenShare"), "info");
      } else {
        showToast(t("incident.shareUnavailable"), "error");
      }
    } catch {
      showToast(t("errors.generic"), "error");
    } finally {
      setSharing(false);
    }
  };

  return (
    <View testID={testID}>
      <View style={styles.card} onLayout={onLayout}>
        <Pressable onPress={() => setViewer(true)} accessibilityRole="imagebutton">
          <Image source={{ uri: photoUrl }} style={{ width: "100%", height: h }} resizeMode="cover" onLoad={onImgLoad} />
        </Pressable>

        {/* plate boxes — tappable to edit */}
        {plates.map((p) => (
          <Pressable
            key={p.id}
            testID={`plate-box-${p.id}`}
            onPress={() => onPlatePress?.(p)}
            style={[
              styles.abs,
              styles.plateBox,
              {
                left: `${p.x * 100}%`,
                top: `${p.y * 100}%`,
                width: `${p.w * 100}%`,
                height: `${p.h * 100}%`,
              },
            ]}
          >
            <View style={styles.plateTag}>
              <Text style={styles.plateTagText} numberOfLines={1}>
                {p.text || "?"}
              </Text>
              <Pencil size={11} color="#FFFFFF" strokeWidth={2.6} />
            </View>
          </Pressable>
        ))}

        {/* face boxes / masks */}
        {faces.map((f) =>
          blur ? (
            <FaceMask key={f.id} face={f} box />
          ) : (
            <View
              key={f.id}
              pointerEvents="none"
              testID={`face-box-${f.id}`}
              style={[
                styles.abs,
                styles.faceBox,
                {
                  left: `${f.x * 100}%`,
                  top: `${f.y * 100}%`,
                  width: `${f.w * 100}%`,
                  height: `${f.h * 100}%`,
                },
              ]}
            />
          ),
        )}

        <View style={styles.expandPill}>
          <Maximize2 size={14} color="#FFFFFF" strokeWidth={2.6} />
        </View>
        <View style={styles.brandPill}>
          <Image source={LOGO} style={styles.brandLogo} resizeMode="contain" />
          <Text style={styles.brandText}>HogoPlus</Text>
        </View>
      </View>

      {/* controls */}
      <View style={styles.controls}>
        {hasFaces ? (
          <Pressable
            testID="blur-faces-toggle"
            onPress={() => setBlur((v) => !v)}
            style={[styles.ctrlBtn, blur && styles.ctrlBtnActive]}
            accessibilityRole="button"
          >
            <EyeOff size={16} color={blur ? "#FFFFFF" : colors.primary} strokeWidth={2.4} />
            <Text style={[styles.ctrlText, blur && styles.ctrlTextActive]}>
              {blur ? t("incident.facesBlurred") : t("incident.blurFaces")}
            </Text>
          </Pressable>
        ) : null}
        <Pressable
          testID="share-photo-button"
          onPress={() => void share()}
          disabled={sharing}
          style={[styles.ctrlBtn, sharing && { opacity: 0.6 }]}
          accessibilityRole="button"
        >
          <Share2 size={16} color={colors.primary} strokeWidth={2.4} />
          <Text style={styles.ctrlText}>{t("incident.share")}</Text>
        </Pressable>
      </View>
      {plates.length > 0 ? (
        <Text style={styles.hint} testID="plate-edit-hint">
          {t("incident.tapPlateToEdit")}
        </Text>
      ) : null}

      {/* OFF-SCREEN capture surface — faces ALWAYS redacted for a shared file */}
      <View style={styles.offscreen} pointerEvents="none">
        <ViewShot ref={shotRef} style={{ width: CAPTURE_WIDTH, height: CAPTURE_WIDTH / aspect }}>
          <Image
            source={{ uri: photoUrl }}
            style={{ width: CAPTURE_WIDTH, height: CAPTURE_WIDTH / aspect }}
            resizeMode="cover"
          />
          {faces.map((f) => (
            <FaceMask key={`cap-${f.id}`} face={f} box={false} />
          ))}
        </ViewShot>
      </View>

      <MediaViewerModal uri={viewer ? photoUrl : null} kind="photo" onClose={() => setViewer(false)} />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 14,
    borderWidth: 2,
    borderColor: colors.primary,
    overflow: "hidden",
    backgroundColor: colors.surface,
    shadowColor: "#000",
    shadowOpacity: 0.15,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
    elevation: 4,
  },
  abs: { position: "absolute" },
  plateBox: {
    borderWidth: 2.5,
    borderColor: colors.accent,
    borderRadius: 4,
    justifyContent: "flex-start",
  },
  plateTag: {
    position: "absolute",
    top: -22,
    left: -2,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    maxWidth: 160,
    backgroundColor: colors.accent,
    borderRadius: radius.sm,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  plateTagText: { fontFamily: fonts.bold, fontSize: 11, color: "#FFFFFF" },
  faceBox: {
    borderWidth: 2,
    borderColor: colors.warning,
    borderRadius: 6,
    backgroundColor: "rgba(0,0,0,0.04)",
  },
  faceMask: {
    borderRadius: 8,
    backgroundColor: "#AEB4BE",
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
  },
  faceMaskOutline: { borderWidth: 1.5, borderColor: "#6B7280" },
  faceMaskInner: {
    width: "70%",
    height: "70%",
    borderRadius: 6,
    backgroundColor: "#C8CCD4",
  },
  expandPill: {
    position: "absolute",
    top: 8,
    left: 8,
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  brandPill: {
    position: "absolute",
    bottom: 8,
    right: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "rgba(17,24,39,0.65)",
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  brandLogo: { width: 18, height: 15 },
  brandText: { fontFamily: fonts.bold, fontSize: 9, color: "#FFFFFF", letterSpacing: 0.3 },
  controls: {
    flexDirection: "row",
    gap: 8,
    marginTop: 8,
  },
  ctrlBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1.5,
    borderColor: colors.primary,
    borderRadius: radius.pill,
    paddingHorizontal: 14,
    paddingVertical: 8,
    minHeight: 40,
  },
  ctrlBtnActive: { backgroundColor: colors.primary },
  ctrlText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.primary },
  ctrlTextActive: { color: "#FFFFFF" },
  hint: { fontFamily: fonts.regular, fontSize: type.xs, color: colors.muted, marginTop: 6 },
  offscreen: { position: "absolute", left: -10000, top: 0, opacity: 0 },
});
