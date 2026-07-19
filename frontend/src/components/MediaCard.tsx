import { useVideoPlayer, VideoView } from "expo-video";
import { Maximize2, Play, X } from "lucide-react-native";
import React, { useState } from "react";
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { colors, fonts, radius } from "@/src/theme/tokens";

const LOGO = require("@/assets/images/logo.png");

function FullVideo({ uri }: { uri: string }) {
  const player = useVideoPlayer(uri, (p) => {
    p.loop = false;
    p.play();
  });
  return (
    <VideoView
      player={player}
      style={styles.viewerMedia}
      nativeControls
      contentFit="contain"
      testID="media-viewer-video"
    />
  );
}

/** Full-screen media viewer (photo: pinch-zoom where supported; video: native controls). */
export function MediaViewerModal({
  uri,
  kind,
  onClose,
}: {
  uri: string | null;
  kind: "photo" | "video";
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal visible={!!uri} animationType="fade" onRequestClose={onClose}>
      <View style={styles.viewerWrap} testID="media-viewer">
        {uri ? (
          kind === "video" ? (
            <FullVideo uri={uri} />
          ) : (
            <ScrollView
              style={{ flex: 1 }}
              contentContainerStyle={styles.zoomContent}
              maximumZoomScale={4}
              minimumZoomScale={1}
              centerContent
            >
              <Image
                source={{ uri }}
                style={styles.viewerMedia}
                resizeMode="contain"
                testID="media-viewer-image"
              />
            </ScrollView>
          )
        ) : null}
        <Pressable
          onPress={onClose}
          style={styles.closeBtn}
          testID="media-viewer-close"
          accessibilityRole="button"
          accessibilityLabel={t("media.close")}
        >
          <X size={26} color="#FFFFFF" strokeWidth={2.5} />
        </Pressable>
      </View>
    </Modal>
  );
}

interface Props {
  uri: string;
  kind?: "photo" | "video";
  height?: number;
  testID?: string;
}

/**
 * Branded media card: 14px radius, 2px brand-blue border, soft shadow, expand
 * affordance + "HogoPlus" eye badge (UI-only). Tap opens the full-screen viewer.
 */
export function MediaCard({ uri, kind = "photo", height = 200, testID = "media-card" }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        style={({ pressed }) => [styles.card, { opacity: pressed ? 0.9 : 1 }]}
        testID={testID}
        accessibilityRole="imagebutton"
        accessibilityLabel={t("media.viewFull")}
      >
        {kind === "video" ? (
          <View style={[styles.videoPoster, { height }]}>
            <View style={styles.playCircle}>
              <Play size={28} color="#FFFFFF" strokeWidth={2.4} fill="#FFFFFF" />
            </View>
          </View>
        ) : (
          <Image source={{ uri }} style={{ width: "100%", height }} resizeMode="cover" />
        )}
        <View style={styles.expandPill}>
          <Maximize2 size={14} color="#FFFFFF" strokeWidth={2.6} />
        </View>
        <View style={styles.brandPill}>
          <Image source={LOGO} style={styles.brandLogo} resizeMode="contain" />
          <Text style={styles.brandText}>HogoPlus</Text>
        </View>
      </Pressable>
      <MediaViewerModal uri={open ? uri : null} kind={kind} onClose={() => setOpen(false)} />
    </>
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
  videoPoster: {
    width: "100%",
    backgroundColor: "#101826",
    alignItems: "center",
    justifyContent: "center",
  },
  playCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: "rgba(58,93,174,0.9)",
    alignItems: "center",
    justifyContent: "center",
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
  viewerWrap: { flex: 1, backgroundColor: "#000000" },
  zoomContent: { flexGrow: 1, alignItems: "center", justifyContent: "center" },
  viewerMedia: { flex: 1, width: "100%" },
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
