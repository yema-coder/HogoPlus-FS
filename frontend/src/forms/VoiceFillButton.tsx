import {
  AudioModule,
  RecordingPresets,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from "expo-audio";
import { Mic, Square, X } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useTranslation } from "react-i18next";

import { uploadFile } from "@/src/api/client";
import { aiVoiceFill } from "@/src/api/endpoints";
import { showToast } from "@/src/components/Toast";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

const MAX_SECONDS = 60;

interface Props {
  formDefinitionId: string;
  onFilled: (fields: Record<string, unknown>) => void;
  testID: string;
}

/** "बोलून भरा" mic FAB: record ≤60s → /api/ai/voice-fill → prefill fields with AI chips. */
export function VoiceFillButton({ formDefinitionId, onFilled, testID }: Props) {
  const { t } = useTranslation();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recState = useAudioRecorderState(recorder, 500);
  const [open, setOpen] = useState(false);
  const [processing, setProcessing] = useState(false);

  const seconds = Math.min(MAX_SECONDS, Math.floor((recState.durationMillis ?? 0) / 1000));

  useEffect(() => {
    if (recState.isRecording && (recState.durationMillis ?? 0) >= MAX_SECONDS * 1000) {
      void finish();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recState.durationMillis, recState.isRecording]);

  const start = async () => {
    try {
      let perm = await AudioModule.getRecordingPermissionsAsync();
      if (!perm.granted && perm.canAskAgain) {
        perm = await AudioModule.requestRecordingPermissionsAsync();
      }
      if (!perm.granted) {
        showToast(t("forms.micDenied"), "error");
        return;
      }
      setOpen(true);
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
    } catch {
      setOpen(false);
      showToast(t("errors.generic"), "error");
    }
  };

  const cancel = async () => {
    try {
      if (recState.isRecording) await recorder.stop();
      await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
    } catch {
      // ignore
    }
    setOpen(false);
    setProcessing(false);
  };

  const finish = async () => {
    try {
      await recorder.stop();
      await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
      const uri = recorder.uri;
      if (!uri) {
        setOpen(false);
        return;
      }
      setProcessing(true);
      const uploaded = await uploadFile(uri, "voicefill.m4a");
      const result = await aiVoiceFill(uploaded.key, formDefinitionId);
      const n = Object.keys(result.fields).length;
      if (n > 0) {
        onFilled(result.fields);
        showToast(t("ai.voiceApplied", { n }), "success");
      } else {
        showToast(t("ai.voiceNone"), "info");
      }
    } catch {
      showToast(t("ai.voiceNone"), "info");
    } finally {
      setOpen(false);
      setProcessing(false);
    }
  };

  return (
    <>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={t("ai.voiceFill")}
        onPress={() => void start()}
        style={({ pressed }) => [styles.fab, pressed && { transform: [{ scale: 0.96 }] }]}
      >
        <Mic size={22} color={colors.onPrimary} strokeWidth={2.4} />
        <Text style={styles.fabText}>{t("ai.voiceFill")}</Text>
      </Pressable>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => void cancel()}>
        <View style={styles.backdrop}>
          <View style={styles.card} testID={`${testID}-modal`}>
            {processing ? (
              <>
                <ActivityIndicator size="large" color={colors.primary} />
                <Text style={styles.title}>{t("ai.voiceProcessing")}</Text>
              </>
            ) : (
              <>
                <View style={styles.pulseDot} />
                <Text style={styles.title}>{t("ai.voiceListening", { s: seconds })}</Text>
                <Text style={styles.hint}>{t("ai.voiceHint")}</Text>
                <View style={styles.row}>
                  <Pressable testID={`${testID}-cancel`} onPress={() => void cancel()} style={styles.cancelBtn}>
                    <X size={22} color={colors.text} strokeWidth={2.4} />
                    <Text style={styles.cancelText}>{t("common.cancel")}</Text>
                  </Pressable>
                  <Pressable testID={`${testID}-done`} onPress={() => void finish()} style={styles.doneBtn}>
                    <Square size={20} color="#FFFFFF" strokeWidth={2.4} fill="#FFFFFF" />
                    <Text style={styles.doneText}>{t("forms.stop")}</Text>
                  </Pressable>
                </View>
              </>
            )}
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  fab: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.xl,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: 52,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    paddingHorizontal: spacing.lg,
    elevation: 5,
  },
  fabText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.onPrimary },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
  },
  card: {
    width: "100%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: "center",
    gap: spacing.md,
  },
  pulseDot: { width: 18, height: 18, borderRadius: 9, backgroundColor: colors.danger },
  title: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, textAlign: "center" },
  hint: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.muted, textAlign: "center" },
  row: { flexDirection: "row", gap: spacing.md, marginTop: spacing.sm },
  cancelBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
  },
  cancelText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  doneBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    minHeight: 48,
    borderRadius: radius.md,
    backgroundColor: colors.danger,
    paddingHorizontal: spacing.xl,
  },
  doneText: { fontFamily: fonts.bold, fontSize: type.base, color: "#FFFFFF" },
});
