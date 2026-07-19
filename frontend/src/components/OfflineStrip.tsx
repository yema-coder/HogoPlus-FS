import NetInfo from "@react-native-community/netinfo";
import { WifiOff } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { colors, fonts, spacing } from "@/src/theme/tokens";

/** Thin app-wide banner while connectivity is lost; auto-hides on reconnect.
 * Ties into the existing offline outbox — work is saved and synced later. */
export function OfflineStrip() {
  const { t } = useTranslation();
  const insets = useSafeAreaInsets();
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const sub = NetInfo.addEventListener((state) => {
      setOffline(state.isConnected === false);
    });
    return () => sub();
  }, []);

  if (!offline) return null;
  return (
    <View style={[styles.strip, { paddingTop: insets.top + 6 }]} testID="offline-strip">
      <WifiOff size={14} color="#FFFFFF" strokeWidth={2.4} />
      <Text style={styles.text} numberOfLines={2}>
        {t("offline.banner")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: colors.warning,
    paddingVertical: 6,
    paddingHorizontal: spacing.lg,
  },
  text: { fontFamily: fonts.semiBold, fontSize: 12, color: "#FFFFFF", flexShrink: 1 },
});
