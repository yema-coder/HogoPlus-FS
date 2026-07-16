import dayjs from "dayjs";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as Haptics from "expo-haptics";
import { Camera as CameraIcon, RefreshCcw, Settings } from "lucide-react-native";
import React, { useRef, useState } from "react";
import {
  Image,
  Linking,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { EyeLoader } from "@/src/components/EyeLoader";
import { showToast } from "@/src/components/Toast";
import { useAuthStore } from "@/src/stores/authStore";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { burnInAndCompress } from "@/src/utils/burnIn";

interface Shot {
  uri: string;
  width: number;
  height: number;
}

interface Props {
  visible: boolean;
  /** watermark line label, e.g. the form field or category name */
  label: string;
  onClose: () => void;
  onCaptured: (uri: string) => void;
  testIDPrefix: string;
}

/**
 * Full-screen rear camera → preview with watermark → burn-in + compression.
 * Same pipeline as the incident flow, reusable by any form photo field.
 */
export function PhotoCaptureModal({ visible, label, onClose, onCaptured, testIDPrefix }: Props) {
  const { t } = useTranslation();
  const profile = useAuthStore((s) => s.profile);
  const { width: windowW } = useWindowDimensions();
  const [permission, requestPermission] = useCameraPermissions();
  const [shot, setShot] = useState<Shot | null>(null);
  const [capturedAt, setCapturedAt] = useState(0);
  const [busy, setBusy] = useState(false);
  const cameraRef = useRef<CameraView>(null);
  const watermarkRef = useRef<View>(null);

  const reset = () => {
    setShot(null);
    setBusy(false);
  };

  const capture = async () => {
    if (!cameraRef.current || busy) return;
    setBusy(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.85 });
      if (photo?.uri) {
        setShot({ uri: photo.uri, width: photo.width || 1200, height: photo.height || 1600 });
        setCapturedAt(Date.now());
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => undefined);
      }
    } catch {
      showToast(t("errors.generic"), "error");
    } finally {
      setBusy(false);
    }
  };

  const acceptPhoto = async () => {
    if (!shot || busy) return;
    setBusy(true);
    try {
      const finalUri = await burnInAndCompress(watermarkRef, shot.uri, shot.width, shot.height);
      onCaptured(finalUri);
      reset();
    } catch {
      showToast(t("errors.generic"), "error");
      setBusy(false);
    }
  };

  const body = () => {
    if (!permission) return <View style={styles.fill} />;
    if (!permission.granted) {
      return (
        <View style={styles.permissionWrap} testID={`${testIDPrefix}-camera-permission`}>
          <View style={styles.permissionIcon}>
            <CameraIcon size={40} color={colors.primary} strokeWidth={2} />
          </View>
          <Text style={styles.permissionTitle}>{t("incident.cameraPermissionTitle")}</Text>
          <Text style={styles.permissionBody}>{t("incident.cameraPermissionBody")}</Text>
          {permission.canAskAgain ? (
            <BigButton
              testID={`${testIDPrefix}-grant-camera`}
              label={t("incident.cameraPermissionTitle")}
              icon={CameraIcon}
              onPress={() => void requestPermission()}
            />
          ) : (
            <>
              <Text style={styles.permissionBody}>{t("errors.cameraDenied")}</Text>
              <BigButton
                testID={`${testIDPrefix}-open-settings`}
                label={t("common.openSettings")}
                icon={Settings}
                variant="outline"
                onPress={() => void Linking.openSettings()}
              />
            </>
          )}
        </View>
      );
    }

    if (!shot) {
      return (
        <View style={styles.fill}>
          <CameraView ref={cameraRef} style={styles.fill} facing="back" />
          <SafeAreaView style={styles.overlay}>
            <View style={styles.topRow}>
              <View style={styles.labelChip}>
                <Text style={styles.labelChipText} numberOfLines={1}>
                  {label}
                </Text>
              </View>
            </View>
            <View style={styles.shutterRow}>
              <Pressable
                testID={`${testIDPrefix}-shutter`}
                accessibilityRole="button"
                onPress={() => void capture()}
                style={({ pressed }) => [styles.shutter, { opacity: pressed || busy ? 0.7 : 1 }]}
              >
                <View style={styles.shutterInner} />
              </Pressable>
            </View>
          </SafeAreaView>
        </View>
      );
    }

    const displayW = windowW - sizes.screenPadding * 2;
    const displayH = Math.round((displayW * shot.height) / shot.width);
    return (
      <SafeAreaView style={styles.previewWrap}>
        <View style={{ flex: 1, justifyContent: "center" }}>
          <View
            ref={watermarkRef}
            collapsable={false}
            style={[styles.shotWrap, { width: displayW, height: Math.min(displayH, 560) }]}
          >
            <Image source={{ uri: shot.uri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
            <View style={styles.watermark}>
              <Text style={styles.wmLine1}>HOGO PLUS · {label}</Text>
              <Text style={styles.wmLine2}>{dayjs(capturedAt).format("DD/MM/YYYY HH:mm")}</Text>
              <Text style={styles.wmLine2}>
                {profile?.full_name ?? ""}
                {profile?.emp_id ? ` · ${profile.emp_id}` : ""}
              </Text>
            </View>
          </View>
        </View>
        <View style={styles.actions}>
          <BigButton
            testID={`${testIDPrefix}-retake`}
            label={t("reg.retake")}
            icon={RefreshCcw}
            variant="muted"
            disabled={busy}
            onPress={reset}
            style={{ flex: 1 }}
          />
          <BigButton
            testID={`${testIDPrefix}-use`}
            label={t("reg.usePhoto")}
            variant="primary"
            loading={busy}
            onPress={() => void acceptPhoto()}
            style={{ flex: 2 }}
          />
        </View>
      </SafeAreaView>
    );
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      onRequestClose={() => {
        reset();
        onClose();
      }}
    >
      <View style={styles.fillBg} testID={`${testIDPrefix}-capture-modal`}>
        {busy && !shot ? (
          <View style={styles.busyOverlay}>
            <EyeLoader size={36} color="#FFFFFF" />
          </View>
        ) : null}
        {body()}
        <SafeAreaView style={styles.closeWrap} edges={["top"]}>
          <Pressable
            testID={`${testIDPrefix}-close`}
            accessibilityRole="button"
            accessibilityLabel={t("common.close")}
            onPress={() => {
              reset();
              onClose();
            }}
            style={styles.closeBtn}
          >
            <Text style={styles.closeText}>✕</Text>
          </Pressable>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: "#000000" },
  fillBg: { flex: 1, backgroundColor: colors.background },
  overlay: { ...StyleSheet.absoluteFillObject, justifyContent: "space-between", pointerEvents: "box-none" },
  topRow: {
    flexDirection: "row",
    padding: sizes.screenPadding,
    paddingLeft: 76,
  },
  labelChip: {
    backgroundColor: "rgba(0,0,0,0.6)",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    maxWidth: "90%",
  },
  labelChipText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: "#FFFFFF" },
  shutterRow: { alignItems: "center", paddingBottom: spacing.xl },
  shutter: {
    width: sizes.cameraShutter,
    height: sizes.cameraShutter,
    borderRadius: sizes.cameraShutter / 2,
    borderWidth: 5,
    borderColor: "#FFFFFF",
    alignItems: "center",
    justifyContent: "center",
  },
  shutterInner: {
    width: sizes.cameraShutter - 20,
    height: sizes.cameraShutter - 20,
    borderRadius: (sizes.cameraShutter - 20) / 2,
    backgroundColor: colors.primary,
  },
  permissionWrap: {
    flex: 1,
    justifyContent: "center",
    padding: sizes.screenPadding,
    gap: spacing.lg,
  },
  permissionIcon: {
    alignSelf: "center",
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  permissionTitle: {
    fontFamily: fonts.bold,
    fontSize: type.xl,
    color: colors.text,
    textAlign: "center",
  },
  permissionBody: {
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.muted,
    textAlign: "center",
  },
  previewWrap: { flex: 1, padding: sizes.screenPadding, gap: spacing.md },
  shotWrap: {
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: "#000000",
    justifyContent: "flex-end",
    alignSelf: "center",
  },
  watermark: {
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: 1,
  },
  wmLine1: { fontFamily: fonts.bold, fontSize: 15, color: "#FFFFFF" },
  wmLine2: { fontFamily: fonts.medium, fontSize: 13, color: "#FFFFFF" },
  actions: { flexDirection: "row", gap: spacing.md },
  busyOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.4)",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 5,
  },
  closeWrap: { position: "absolute", top: 0, left: 0 },
  closeBtn: {
    width: 56,
    height: 56,
    margin: spacing.sm,
    borderRadius: 28,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
  },
  closeText: { fontFamily: fonts.bold, fontSize: 24, color: "#FFFFFF" },
});
