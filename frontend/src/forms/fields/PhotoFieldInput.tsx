import { Camera as CameraIcon, RefreshCcw } from "lucide-react-native";
import React, { useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { fileUrl } from "@/src/api/client";
import { PhotoCaptureModal } from "@/src/components/PhotoCaptureModal";
import { isLocalUri } from "@/src/forms/draft";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

interface Props {
  label: string;
  value: string | undefined; // local uri (pre-upload) or server file key
  onChange: (v: string) => void;
  error?: boolean;
  testID: string;
}

export function PhotoFieldInput({ label, value, onChange, error, testID }: Props) {
  const { t } = useTranslation();
  const [cameraOpen, setCameraOpen] = useState(false);
  const displayUri = value ? (isLocalUri(value) ? value : fileUrl(value)) : null;

  return (
    <View style={styles.wrap}>
      {displayUri ? (
        <View style={styles.thumbRow}>
          <Image source={{ uri: displayUri }} style={styles.thumb} resizeMode="cover" />
          <Pressable
            testID={`${testID}-retake`}
            accessibilityRole="button"
            onPress={() => setCameraOpen(true)}
            style={styles.retakeBtn}
          >
            <RefreshCcw size={20} color={colors.accent} strokeWidth={2.4} />
            <Text style={styles.retakeText}>{t("reg.retake")}</Text>
          </Pressable>
        </View>
      ) : (
        <Pressable
          testID={testID}
          accessibilityRole="button"
          onPress={() => setCameraOpen(true)}
          style={[styles.takeBtn, error && styles.takeBtnError]}
        >
          <CameraIcon size={26} color={colors.primary} strokeWidth={2.2} />
          <Text style={styles.takeText}>{t("forms.takePhoto")}</Text>
        </Pressable>
      )}
      <PhotoCaptureModal
        visible={cameraOpen}
        label={label}
        onClose={() => setCameraOpen(false)}
        onCaptured={(uri) => {
          onChange(uri);
          setCameraOpen(false);
        }}
        testIDPrefix={testID}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  takeBtn: {
    minHeight: 64,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.primary,
    borderStyle: "dashed",
    backgroundColor: colors.brandTertiary,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
  },
  takeBtnError: { borderColor: colors.danger },
  takeText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.primary },
  thumbRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.md },
  thumb: {
    width: 120,
    height: 120,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  retakeBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.md,
  },
  retakeText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.accent },
});
