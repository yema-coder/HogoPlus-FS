import {
  AudioModule,
  RecordingPresets,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioRecorder,
  useAudioRecorderState,
} from "expo-audio";
import { Mic, Play, RefreshCcw, Settings, Square } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { fileUrl } from "@/src/api/client";
import { showToast } from "@/src/components/Toast";
import { isLocalUri } from "@/src/forms/draft";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

const MAX_SECONDS = 60;

interface Props {
  value: string | undefined; // local uri (pre-upload) or server file key
  onChange: (v: string | undefined) => void;
  error?: boolean;
  testID: string;
}

/** 60s-max voice note: record → timer → play / re-record. Audio only, no transcription. */
export function VoiceFieldInput({ value, onChange, error, testID }: Props) {
  const { t } = useTranslation();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recState = useAudioRecorderState(recorder, 500);
  const player = useAudioPlayer();
  const [blocked, setBlocked] = useState(false);

  const seconds = Math.min(MAX_SECONDS, Math.floor((recState.durationMillis ?? 0) / 1000));

  useEffect(() => {
    if (recState.isRecording && (recState.durationMillis ?? 0) >= MAX_SECONDS * 1000) {
      void stop();
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
        setBlocked(!perm.canAskAgain);
        showToast(t("forms.micDenied"), "error");
        return;
      }
      setBlocked(false);
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
    } catch {
      showToast(t("errors.generic"), "error");
    }
  };

  const stop = async () => {
    try {
      await recorder.stop();
      await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
      if (recorder.uri) onChange(recorder.uri);
    } catch {
      showToast(t("errors.generic"), "error");
    }
  };

  const play = () => {
    if (!value) return;
    try {
      player.replace({ uri: isLocalUri(value) ? value : fileUrl(value) });
      player.play();
    } catch {
      showToast(t("errors.generic"), "error");
    }
  };

  if (recState.isRecording) {
    return (
      <View style={[styles.box, styles.boxRecording]}>
        <View style={styles.recDot} />
        <Text style={styles.recText}>{t("forms.recording", { s: seconds })}</Text>
        <Pressable testID={`${testID}-stop`} onPress={() => void stop()} style={styles.stopBtn}>
          <Square size={22} color="#FFFFFF" strokeWidth={2.4} fill="#FFFFFF" />
          <Text style={styles.stopText}>{t("forms.stop")}</Text>
        </Pressable>
      </View>
    );
  }

  if (value) {
    return (
      <View style={styles.row}>
        <Pressable testID={`${testID}-play`} onPress={play} style={styles.playBtn}>
          <Play size={22} color={colors.onPrimary} strokeWidth={2.4} fill={colors.onPrimary} />
          <Text style={styles.playText}>{t("forms.play")}</Text>
        </Pressable>
        <Pressable testID={`${testID}-rerecord`} onPress={() => void start()} style={styles.reBtn}>
          <RefreshCcw size={20} color={colors.accent} strokeWidth={2.4} />
          <Text style={styles.reText}>{t("forms.reRecord")}</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.wrap}>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        onPress={() => void start()}
        style={[styles.box, error && styles.boxError]}
      >
        <Mic size={26} color={colors.primary} strokeWidth={2.2} />
        <Text style={styles.boxText}>{t("forms.record")}</Text>
      </Pressable>
      {blocked ? (
        <Pressable
          testID={`${testID}-settings`}
          onPress={() => void Linking.openSettings()}
          style={styles.settingsBtn}
        >
          <Settings size={18} color={colors.accent} strokeWidth={2.2} />
          <Text style={styles.settingsText}>{t("common.openSettings")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  box: {
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
    paddingHorizontal: spacing.lg,
  },
  boxError: { borderColor: colors.danger },
  boxText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.primary },
  boxRecording: {
    borderStyle: "solid",
    borderColor: colors.danger,
    backgroundColor: "#FDECEC",
    justifyContent: "space-between",
  },
  recDot: { width: 14, height: 14, borderRadius: 7, backgroundColor: colors.danger },
  recText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.danger, flex: 1, marginLeft: 10 },
  stopBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.danger,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    minHeight: 48,
  },
  stopText: { fontFamily: fonts.bold, fontSize: type.base, color: "#FFFFFF" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  playBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.xl,
    minHeight: sizes.touchTarget,
  },
  playText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.onPrimary },
  reBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.md,
  },
  reText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.accent },
  settingsBtn: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44 },
  settingsText: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.accent },
});
