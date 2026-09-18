import { useRouter } from "expo-router";
import { CheckCircle2, MapPin, Battery, Clock, Eye, Trash2 } from "lucide-react-native";
import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { presenceConsent, presenceMyStatus } from "@/src/api/endpoints";
import { BigButton } from "@/src/components/BigButton";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { showToast } from "@/src/components/Toast";
import { startTracking } from "@/src/presence/tracker";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";
import { storage } from "@/src/utils/storage";

/** v1.0.25 — Live-presence consent. MARATHI FIRST (owner rule), very simple
 * words, versioned, stored server-side. Tracking NEVER starts without it. */

type L = "mr" | "hi" | "en";

const C: Record<
  L,
  { title: string; lead: string; points: { icon: React.ComponentType<any>; text: string }[]; agree: string; later: string; note: string }
> = {
  mr: {
    title: "तुमचं लोकेशन — फक्त शिफ्टमध्ये",
    lead: "कारखान्यात तुम्ही कुठे आहात हे अधिकाऱ्यांना दिसेल. हे फक्त तुमच्या शिफ्टच्या वेळेत.",
    points: [
      { icon: Clock, text: "पंच-इन केल्यावरच सुरू. पंच-आउट झाल्यावर लगेच बंद." },
      { icon: MapPin, text: "शिफ्टच्या बाहेर कधीही ट्रॅकिंग नाही." },
      { icon: Eye, text: "फक्त कारखान्याचे अधिकारी बघू शकतात." },
      { icon: Trash2, text: "३० दिवसांनंतर माहिती आपोआप डिलीट होते." },
      { icon: Battery, text: "बॅटरी खूप कमी वापरते." },
    ],
    agree: "मी सहमत आहे",
    later: "आत्ता नाही",
    note: "तुमच्या संमतीशिवाय ट्रॅकिंग कधीही सुरू होणार नाही.",
  },
  hi: {
    title: "आपका लोकेशन — सिर्फ़ शिफ्ट में",
    lead: "फ़ैक्टरी में आप कहाँ हैं यह अधिकारियों को दिखेगा। सिर्फ़ आपकी शिफ्ट के समय।",
    points: [
      { icon: Clock, text: "पंच-इन पर ही शुरू। पंच-आउट पर तुरंत बंद।" },
      { icon: MapPin, text: "शिफ्ट के बाहर कभी ट्रैकिंग नहीं।" },
      { icon: Eye, text: "सिर्फ़ फ़ैक्टरी के अधिकारी देख सकते हैं।" },
      { icon: Trash2, text: "30 दिन बाद जानकारी अपने-आप डिलीट।" },
      { icon: Battery, text: "बैटरी बहुत कम इस्तेमाल होती है।" },
    ],
    agree: "मैं सहमत हूँ",
    later: "अभी नहीं",
    note: "आपकी सहमति के बिना ट्रैकिंग कभी शुरू नहीं होगी।",
  },
  en: {
    title: "Your location — during shift only",
    lead: "Managers can see where you are inside the factory. Only during your shift.",
    points: [
      { icon: Clock, text: "Starts only at punch-in. Stops right at punch-out." },
      { icon: MapPin, text: "Never tracked outside your shift." },
      { icon: Eye, text: "Only factory management can see it." },
      { icon: Trash2, text: "Data is deleted automatically after 30 days." },
      { icon: Battery, text: "Uses very little battery." },
    ],
    agree: "I agree",
    later: "Not now",
    note: "Tracking will never start without your consent.",
  },
};

export default function PresenceConsentScreen() {
  const router = useRouter();
  const [lang, setLang] = useState<L>("mr"); // Marathi FIRST — owner rule
  const [busy, setBusy] = useState(false);
  const c = C[lang];

  const goHome = () => (router.canGoBack() ? router.back() : router.replace("/(tabs)/home"));

  const agree = async () => {
    setBusy(true);
    try {
      const status = await presenceMyStatus();
      await presenceConsent(status.consent_version, lang);
      const started = await startTracking();
      showToast(
        started
          ? lang === "en" ? "Tracking started — shift only" : lang === "hi" ? "ट्रैकिंग शुरू — सिर्फ़ शिफ्ट में" : "ट्रॅकिंग सुरू — फक्त शिफ्टमध्ये"
          : lang === "en" ? "Saved. Tracking starts at punch-in" : lang === "hi" ? "सेव हुआ। पंच-इन पर शुरू होगा" : "सेव्ह झाले. पंच-इन झाल्यावर सुरू होईल",
        "success",
      );
      goHome();
    } catch {
      showToast(lang === "en" ? "Could not save — try again" : lang === "hi" ? "सेव नहीं हुआ — फिर कोशिश करें" : "सेव्ह झाले नाही — पुन्हा प्रयत्न करा", "error");
    } finally {
      setBusy(false);
    }
  };

  const later = async () => {
    await storage.setItem("hogo.presence.consentDeclinedAt", Date.now()).catch(() => undefined);
    goHome();
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="presence-consent-screen">
      <ScreenHeader title={c.title} onBack={() => void later()} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.langRow}>
          {(["mr", "hi", "en"] as L[]).map((l) => (
            <Pressable
              key={l}
              testID={`consent-lang-${l}`}
              onPress={() => setLang(l)}
              style={[styles.langBtn, lang === l && styles.langOn]}
            >
              <Text style={[styles.langText, lang === l && styles.langTextOn]}>
                {l === "mr" ? "मराठी" : l === "hi" ? "हिंदी" : "English"}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.hero}>
          <MapPin size={44} color={colors.primary} strokeWidth={2.2} />
        </View>
        <Text style={styles.lead}>{c.lead}</Text>
        {c.points.map((p, i) => (
          <View key={i} style={styles.point} testID={`consent-point-${i}`}>
            <p.icon size={24} color={colors.primary} strokeWidth={2.2} />
            <Text style={styles.pointText}>{p.text}</Text>
          </View>
        ))}
        <View style={styles.noteBox}>
          <CheckCircle2 size={18} color={colors.success} strokeWidth={2.4} />
          <Text style={styles.noteText}>{c.note}</Text>
        </View>
      </ScrollView>
      <View style={styles.footer}>
        <BigButton testID="consent-agree-button" label={c.agree} variant="success" loading={busy} onPress={() => void agree()} />
        <Pressable testID="consent-later-button" onPress={() => void later()} style={styles.laterBtn}>
          <Text style={styles.laterText}>{c.later}</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: sizes.screenPadding, gap: spacing.md },
  langRow: { flexDirection: "row", gap: spacing.sm, justifyContent: "center" },
  langBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    minHeight: 44,
    justifyContent: "center",
  },
  langOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  langText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.muted },
  langTextOn: { color: colors.onPrimary },
  hero: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "center",
    marginTop: spacing.sm,
  },
  lead: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
    textAlign: "center",
    marginBottom: spacing.sm,
  },
  point: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  pointText: { flex: 1, fontFamily: fonts.medium, fontSize: type.base, color: colors.text },
  noteBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: "#DDF5E5",
  },
  noteText: { flex: 1, fontFamily: fonts.semiBold, fontSize: type.sm, color: colors.text },
  footer: { padding: sizes.screenPadding, gap: spacing.sm },
  laterBtn: { minHeight: 48, alignItems: "center", justifyContent: "center" },
  laterText: { fontFamily: fonts.bold, fontSize: type.base, color: colors.muted },
});
