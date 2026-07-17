import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { Pause, Play } from "lucide-react-native";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

interface Props {
  uri: string;
  label: string;
  testID: string;
}

const fmt = (s: number) => {
  const v = Math.max(0, Math.floor(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
};

/** Voice-note player: play/pause + progress bar + elapsed/total duration. */
export function AudioPlayerCard({ uri, label, testID }: Props) {
  const player = useAudioPlayer({ uri });
  const status = useAudioPlayerStatus(player);
  const duration = status.duration > 0 ? status.duration : 0;
  const progress = duration > 0 ? Math.min(1, status.currentTime / duration) : 0;

  const toggle = () => {
    if (status.playing) {
      player.pause();
      return;
    }
    if (status.didJustFinish || (duration > 0 && progress >= 1)) {
      void player.seekTo(0);
    }
    player.play();
  };

  return (
    <View style={styles.card} testID={testID}>
      <Pressable
        testID={`${testID}-toggle`}
        accessibilityRole="button"
        accessibilityLabel={label}
        onPress={toggle}
        style={({ pressed }) => [styles.btn, pressed && { opacity: 0.8 }]}
      >
        {status.playing ? (
          <Pause size={22} color={colors.onPrimary} strokeWidth={2.4} fill={colors.onPrimary} />
        ) : (
          <Play size={22} color={colors.onPrimary} strokeWidth={2.4} fill={colors.onPrimary} />
        )}
      </Pressable>
      <View style={styles.body}>
        <Text style={styles.label} numberOfLines={1}>
          {label}
        </Text>
        <View style={styles.track}>
          <View style={[styles.fill, { width: `${progress * 100}%` }]} />
        </View>
        <Text style={styles.time} testID={`${testID}-time`}>
          {fmt(status.currentTime)} / {duration > 0 ? fmt(duration) : "--:--"}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  btn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  body: { flex: 1, gap: 4 },
  label: { fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  track: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceTertiary,
    overflow: "hidden",
  },
  fill: { height: "100%", backgroundColor: colors.primary, borderRadius: 3 },
  time: { fontFamily: fonts.medium, fontSize: 12, color: colors.muted },
});
