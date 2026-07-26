import { CameraView, useCameraPermissions } from "expo-camera";
import { Camera as CameraIcon, RefreshCcw, Settings } from "lucide-react-native";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Linking,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

interface Props {
  hint: string;
  onUse: (uri: string) => void;
  busy?: boolean;
  busyLabel?: string;
  testIDPrefix: string;
  /** Renders a ✕ button over the camera that abandons capture. */
  onClose?: () => void;
}

/** Front-camera selfie capture with face guide, permission contract and preview. */
export function SelfieCamera({ hint, onUse, busy = false, busyLabel, testIDPrefix, onClose }: Props) {
  const { t } = useTranslation();
  const insets = useSafeAreaInsets();
  const [permission, requestPermission] = useCameraPermissions();
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  // Prompt 21 Bug 2: no silent black screens — track camera start explicitly.
  const [cameraReady, setCameraReady] = useState(Platform.OS === "web");
  const [cameraFailed, setCameraFailed] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const autoAsked = useRef(false);
  const cameraRef = useRef<CameraView>(null);

  // Auto-request an undetermined permission on mount — entering this screen IS the
  // user intent (registration has no CaptureGuards wrapper to ask for us).
  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain && !autoAsked.current) {
      autoAsked.current = true;
      void requestPermission();
    }
  }, [permission, requestPermission]);

  // 6-second onCameraReady watchdog (native only): a preview that never starts
  // becomes a visible, retryable error instead of a black screen.
  useEffect(() => {
    if (Platform.OS === "web" || !permission?.granted || photoUri || cameraReady || cameraFailed)
      return;
    const timer = setTimeout(() => setCameraFailed(true), 6000);
    return () => clearTimeout(timer);
  }, [permission?.granted, photoUri, cameraReady, cameraFailed, retryKey]);

  const retryCamera = () => {
    setCameraFailed(false);
    setCameraReady(Platform.OS === "web");
    setRetryKey((k) => k + 1); // force a full CameraView remount
  };

  const capture = async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.7 });
      if (photo?.uri) setPhotoUri(photo.uri);
    } catch {
      // camera failure — stay on screen
    } finally {
      setCapturing(false);
    }
  };

  if (!permission) {
    // permission state still loading — never a bare black view
    return (
      <View style={[styles.fill, styles.center]} testID={`${testIDPrefix}-loading`}>
        <ActivityIndicator size="large" color="#FFFFFF" />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.permissionWrap} testID={`${testIDPrefix}-permission`}>
        <View style={styles.permissionIcon}>
          <CameraIcon size={40} color={colors.primary} strokeWidth={2} />
        </View>
        <Text style={styles.permissionTitle}>{t("incident.cameraPermissionTitle")}</Text>
        <Text style={styles.permissionBody}>{hint}</Text>
        {permission.canAskAgain ? (
          <BigButton
            testID={`${testIDPrefix}-grant-camera-button`}
            label={t("incident.cameraPermissionTitle")}
            icon={CameraIcon}
            onPress={() => void requestPermission()}
          />
        ) : (
          <>
            <Text style={styles.permissionBody}>{t("errors.cameraDenied")}</Text>
            <BigButton
              testID={`${testIDPrefix}-open-settings-button`}
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

  if (photoUri) {
    return (
      <View style={styles.fill} testID={`${testIDPrefix}-preview`}>
        <Image source={{ uri: photoUri }} style={styles.preview} />
        <View style={styles.previewActions}>
          <BigButton
            testID={`${testIDPrefix}-retake-button`}
            label={t("reg.retake")}
            icon={RefreshCcw}
            variant="muted"
            onPress={() => setPhotoUri(null)}
            disabled={busy}
            style={{ flex: 1 }}
          />
          <BigButton
            testID={`${testIDPrefix}-use-photo-button`}
            label={busy ? (busyLabel ?? t("att.uploading")) : t("reg.usePhoto")}
            variant="success"
            onPress={() => onUse(photoUri)}
            loading={busy}
            style={{ flex: 1 }}
          />
        </View>
      </View>
    );
  }

  if (cameraFailed) {
    return (
      <View style={styles.permissionWrap} testID={`${testIDPrefix}-camera-error`}>
        <View style={styles.permissionIcon}>
          <CameraIcon size={40} color={colors.danger} strokeWidth={2} />
        </View>
        <Text style={styles.permissionTitle}>{t("errors.cameraStart")}</Text>
        <BigButton
          testID={`${testIDPrefix}-camera-retry-button`}
          label={t("common.retry")}
          icon={RefreshCcw}
          onPress={retryCamera}
        />
        <BigButton
          testID={`${testIDPrefix}-camera-settings-button`}
          label={t("common.openSettings")}
          icon={Settings}
          variant="outline"
          onPress={() => void Linking.openSettings()}
        />
      </View>
    );
  }

  return (
    <View style={styles.fill} testID={`${testIDPrefix}-camera`}>
      <CameraView
        key={retryKey}
        ref={cameraRef}
        style={styles.fill}
        facing="front"
        onCameraReady={() => setCameraReady(true)}
        onMountError={() => setCameraFailed(true)}
      />
      {!cameraReady ? (
        <View style={[StyleSheet.absoluteFillObject, styles.center]} pointerEvents="none">
          <ActivityIndicator size="large" color="#FFFFFF" />
        </View>
      ) : null}
      <View style={styles.overlay}>
        <View style={styles.faceGuide} />
        <Text style={styles.guideText}>{hint}</Text>
      </View>
      {onClose ? (
        <Pressable
          testID={`${testIDPrefix}-close-button`}
          accessibilityRole="button"
          accessibilityLabel={t("common.close")}
          onPress={onClose}
          style={[styles.closeBtn, { top: Math.max(insets.top, spacing.md) + spacing.xs }]}
        >
          <Text style={styles.closeText}>✕</Text>
        </Pressable>
      ) : null}
      <View style={styles.shutterRow}>
        <Pressable
          testID={`${testIDPrefix}-shutter-button`}
          accessibilityRole="button"
          onPress={() => void capture()}
          style={({ pressed }) => [styles.shutter, { opacity: pressed || capturing ? 0.7 : 1 }]}
        >
          <View style={styles.shutterInner} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: "#000000" },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    pointerEvents: "none",
  },
  faceGuide: {
    width: 260,
    height: 330,
    borderRadius: 165,
    borderWidth: 3,
    borderColor: "rgba(255,255,255,0.85)",
    borderStyle: "dashed",
  },
  guideText: {
    marginTop: spacing.lg,
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: "#FFFFFF",
    textAlign: "center",
    backgroundColor: "rgba(0,0,0,0.5)",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  shutterRow: {
    position: "absolute",
    bottom: spacing.xl,
    left: 0,
    right: 0,
    alignItems: "center",
  },
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
    backgroundColor: "#FFFFFF",
  },
  permissionWrap: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: "stretch",
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
  preview: { flex: 1 },
  closeBtn: {
    position: "absolute",
    left: spacing.md,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
  },
  closeText: { fontFamily: fonts.bold, fontSize: 24, color: "#FFFFFF" },
  previewActions: {
    flexDirection: "row",
    gap: spacing.md,
    padding: sizes.screenPadding,
    backgroundColor: colors.background,
  },
});
