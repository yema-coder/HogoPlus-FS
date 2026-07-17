import { Camera as CameraIcon } from "lucide-react-native";
import React, { useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { useTranslation } from "react-i18next";

import { uploadFile } from "@/src/api/client";
import { aiAnpr } from "@/src/api/endpoints";
import { EyeLoader } from "@/src/components/EyeLoader";
import { PhotoCaptureModal } from "@/src/components/PhotoCaptureModal";
import { TextFieldInput } from "@/src/forms/fields/TextFieldInput";
import { colors, radius, sizes } from "@/src/theme/tokens";

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onAiFilled: (confidence: number) => void;
  onAiLoading: (loading: boolean) => void;
  error?: boolean;
  testID: string;
}

/** Text input + camera scan for ai_hook=anpr: photo → /api/ai/anpr → auto-fill plate.
 *  Auto-fill never locks the field; AI failure falls back silently to manual entry. */
export function AnprTextInput({ label, value, onChange, onAiFilled, onAiLoading, error, testID }: Props) {
  const { t } = useTranslation();
  const [cameraOpen, setCameraOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const scan = async (uri: string) => {
    setBusy(true);
    onAiLoading(true);
    try {
      const uploaded = await uploadFile(uri, "anpr.jpg");
      const result = await aiAnpr(uploaded.key);
      if (result.valid && result.plate) {
        onChange(result.plate);
        onAiFilled(result.confidence);
      }
    } catch {
      // silent fallback to manual entry — no error popup
    } finally {
      setBusy(false);
      onAiLoading(false);
    }
  };

  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <TextFieldInput value={value} onChange={onChange} error={error} testID={testID} />
      </View>
      <Pressable
        testID={`${testID}-scan`}
        accessibilityRole="button"
        accessibilityLabel={t("ai.scanPlate")}
        disabled={busy}
        onPress={() => setCameraOpen(true)}
        style={[styles.scanBtn, busy && { opacity: 0.6 }]}
      >
        {busy ? (
          <EyeLoader size={14} />
        ) : (
          <CameraIcon size={24} color={colors.onPrimary} strokeWidth={2.2} />
        )}
      </Pressable>
      <PhotoCaptureModal
        visible={cameraOpen}
        label={label}
        onClose={() => setCameraOpen(false)}
        onCaptured={(uri) => {
          setCameraOpen(false);
          void scan(uri);
        }}
        testIDPrefix={`${testID}-scan`}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  scanBtn: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    borderRadius: radius.md,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
});
