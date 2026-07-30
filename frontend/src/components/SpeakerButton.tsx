import { setAudioModeAsync, useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { Square, Volume2 } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { Pressable, StyleSheet, type StyleProp, type ViewStyle } from "react-native";
import { useTranslation } from "react-i18next";

import { ApiError, localizedDetail } from "@/src/api/client";
import { EyeLoader } from "@/src/components/EyeLoader";
import { showToast } from "@/src/components/Toast";
import i18n from "@/src/i18n";
import { colors } from "@/src/theme/tokens";
import { getTtsUri } from "@/src/utils/ttsCache";

interface Props {
  text: string;
  size?: number;
  testID?: string;
  style?: StyleProp<ViewStyle>;
}

/** Read-aloud button (v1.0.21): an obvious speaker ICON — zero reading needed.
 * Audio is cached by text hash on the server AND on-device, so repeat plays
 * cost nothing and work offline. Tap again while playing = stop. */
export function SpeakerButton({ text, size = 44, testID, style }: Props) {
  const { t } = useTranslation();
  const player = useAudioPlayer();
  const status = useAudioPlayerStatus(player);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (status.didJustFinish) setPlaying(false);
  }, [status.didJustFinish]);

  const onPress = async () => {
    if (playing) {
      player.pause();
      setPlaying(false);
      return;
    }
    if (loading || !text.trim()) return;
    setLoading(true);
    try {
      const uri = await getTtsUri(text.trim());
      await setAudioModeAsync({ playsInSilentMode: true }).catch(() => undefined);
      player.replace({ uri });
      player.seekTo(0);
      player.play();
      setPlaying(true);
    } catch (e) {
      const msg = localizedDetail(e, i18n.language || "en");
      const offline = e instanceof ApiError && e.status === 0;
      showToast(msg ?? t(offline ? "voice.ttsOffline" : "voice.ttsUnavailable"), "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={t("voice.listen")}
      onPress={() => void onPress()}
      hitSlop={8}
      style={({ pressed }) => [
        styles.btn,
        { width: size, height: size, borderRadius: size / 2, opacity: pressed ? 0.7 : 1 },
        playing && styles.btnActive,
        style,
      ]}
    >
      {loading ? (
        <EyeLoader size={Math.round(size * 0.45)} />
      ) : playing ? (
        <Square
          size={Math.round(size * 0.4)}
          color="#FFFFFF"
          strokeWidth={2.4}
          fill="#FFFFFF"
        />
      ) : (
        <Volume2 size={Math.round(size * 0.52)} color={colors.primary} strokeWidth={2.4} />
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "center",
  },
  btnActive: { backgroundColor: colors.primary },
});
