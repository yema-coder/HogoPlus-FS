import { BatteryCharging, Settings2, Smartphone } from "lucide-react-native";
import React from "react";
import { Linking, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

/** v1.0.25 — OEM battery / auto-start instructions so aggressive Android
 * battery savers (Xiaomi/Vivo/Oppo/Realme/Samsung) don't kill the shift
 * tracking foreground service. Trilingual via i18n. */

const pick = (lang: string, mr: string, hi: string, en: string) =>
  lang === "mr" ? mr : lang === "hi" ? hi : en;

export default function BatteryHelpScreen() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;

  const oems: { name: string; steps: string }[] = [
    {
      name: "Xiaomi / Redmi / POCO",
      steps: pick(
        lang,
        "सेटिंग्ज → Apps → HogoPlus-FS → Battery saver → No restrictions निवडा. Autostart पण चालू करा.",
        "सेटिंग्स → Apps → HogoPlus-FS → Battery saver → No restrictions चुनें। Autostart भी चालू करें।",
        "Settings → Apps → HogoPlus-FS → Battery saver → choose No restrictions. Also turn ON Autostart.",
      ),
    },
    {
      name: "Vivo / iQOO",
      steps: pick(
        lang,
        "सेटिंग्ज → Battery → Background power consumption → HogoPlus-FS ला परवानगी द्या. i Manager → Autostart चालू करा.",
        "सेटिंग्स → Battery → Background power consumption → HogoPlus-FS को अनुमति दें। i Manager → Autostart चालू करें।",
        "Settings → Battery → Background power consumption → allow HogoPlus-FS. i Manager → turn ON Autostart.",
      ),
    },
    {
      name: "Oppo",
      steps: pick(
        lang,
        "सेटिंग्ज → Battery → App battery management → HogoPlus-FS → Don't optimize. Startup manager मध्ये app ला परवानगी द्या.",
        "सेटिंग्स → Battery → App battery management → HogoPlus-FS → Don't optimize। Startup manager में app को अनुमति दें।",
        "Settings → Battery → App battery management → HogoPlus-FS → Don't optimize. Allow the app in Startup manager.",
      ),
    },
    {
      name: "Realme",
      steps: pick(
        lang,
        "सेटिंग्ज → Battery → App battery management → HogoPlus-FS → Allow background activity. Auto-start चालू करा.",
        "सेटिंग्स → Battery → App battery management → HogoPlus-FS → Allow background activity। Auto-start चालू करें।",
        "Settings → Battery → App battery management → HogoPlus-FS → Allow background activity. Turn ON Auto-start.",
      ),
    },
    {
      name: "Samsung",
      steps: pick(
        lang,
        "सेटिंग्ज → Apps → HogoPlus-FS → Battery → Unrestricted निवडा. 'Put app to sleep' बंद ठेवा.",
        "सेटिंग्स → Apps → HogoPlus-FS → Battery → Unrestricted चुनें। 'Put app to sleep' बंद रखें।",
        "Settings → Apps → HogoPlus-FS → Battery → choose Unrestricted. Keep 'Put app to sleep' OFF.",
      ),
    },
  ];

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="battery-help-screen">
      <ScreenHeader title={t("presence.batteryTitle")} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.hero}>
          <BatteryCharging size={40} color={colors.primary} strokeWidth={2.2} />
        </View>
        <Text style={styles.lead}>{t("presence.batteryLead")}</Text>
        {oems.map((o) => (
          <View key={o.name} style={styles.card} testID={`oem-${o.name.split(" ")[0].toLowerCase()}`}>
            <View style={styles.cardHead}>
              <Smartphone size={20} color={colors.primary} strokeWidth={2.2} />
              <Text style={styles.cardTitle}>{o.name}</Text>
            </View>
            <Text style={styles.cardBody}>{o.steps}</Text>
          </View>
        ))}
        <View style={{ height: spacing.sm }} />
        <BigButton
          testID="open-settings-button"
          label={t("presence.openSettings")}
          icon={Settings2}
          onPress={() => void Linking.openSettings()}
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md },
  hero: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "center",
  },
  lead: {
    fontFamily: fonts.semiBold,
    fontSize: type.base,
    color: colors.text,
    textAlign: "center",
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  cardTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text },
  cardBody: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted, lineHeight: 22 },
});
