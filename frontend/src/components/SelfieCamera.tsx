import { CameraView, useCameraPermissions } from "expo-camera";
import { Camera as CameraIcon, RefreshCcw, Settings } from "lucide-react-native";
import React, { useRef, useState } from "react";
import { Image, Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

interface Props {
  hint: string;
  onUse: (uri: string) => void;
  busy?: boolean;
  busyLabel?: string;
  testIDPrefix: string;
}

/** Front-camera selfie capture with face guide, permission contract and preview. */
export function SelfieCamera({ hint, onUse, busy = false, busyLabel, testIDPrefix }: Props) {
  const { t } = useTranslation();
  const [permission, requestPermission] = useCameraPermissions();
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const cameraRef = useRef<CameraView>(null);

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

  if (!permission) return <View style={styles.fill} />;

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

  return (
    <View style={styles.fill} testID={`${testIDPrefix}-camera`}>
      <CameraView ref={cameraRef} style={styles.fill} facing="front" />
      <View pointerEvents="none" style={styles.overlay}>
        <View style={styles.faceGuide} />
        <Text style={styles.guideText}>{hint}</Text>
      </View>
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
  previewActions: {
    flexDirection: "row",
    gap: spacing.md,
    padding: sizes.screenPadding,
    backgroundColor: colors.background,
  },
});
