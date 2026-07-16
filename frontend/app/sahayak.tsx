import { MessageCircleQuestion, Send } from "lucide-react-native";
import React, { useRef, useState } from "react";
import {
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { aiChat } from "@/src/api/endpoints";
import type { ChatCitation } from "@/src/api/types";
import { EyeLoader } from "@/src/components/EyeLoader";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

interface Bubble {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  citations?: ChatCitation[];
}

/** Sahayak — trilingual SOP RAG chat (user right, answer left with doc-citation chips). */
export default function SahayakScreen() {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<string | null>(null);
  const listRef = useRef<FlatList<Bubble>>(null);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: text }]);
    try {
      const res = await aiChat(text, conversationId.current);
      conversationId.current = res.conversation_id;
      setMessages((prev) => [
        ...prev,
        { id: `a-${Date.now()}`, role: "assistant", content: res.answer, citations: res.citations },
      ]);
    } catch {
      setMessages((prev) => [...prev, { id: `e-${Date.now()}`, role: "error", content: t("sahayak.error") }]);
    } finally {
      setBusy(false);
    }
  };

  const renderItem = ({ item }: { item: Bubble }) => {
    if (item.role === "user") {
      return (
        <View style={[styles.bubble, styles.userBubble]}>
          <Text style={styles.userText}>{item.content}</Text>
        </View>
      );
    }
    return (
      <View style={[styles.bubble, styles.botBubble, item.role === "error" && styles.errorBubble]}>
        <Text style={styles.botText}>{item.content}</Text>
        {item.citations && item.citations.length > 0 ? (
          <View style={styles.citeRow}>
            {item.citations.map((c, i) => (
              <View key={`${c.doc_title}-${c.page}-${i}`} style={styles.citeChip}>
                <Text style={styles.citeText} numberOfLines={1}>
                  {c.doc_title} · {t("sahayak.page")} {c.page}
                </Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="sahayak-screen">
      <ScreenHeader title={t("sahayak.title")} />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={Platform.OS === "ios" ? 90 : 0}
      >
        {messages.length === 0 ? (
          <View style={styles.empty}>
            <View style={styles.emptyIcon}>
              <MessageCircleQuestion size={44} color={colors.primary} strokeWidth={1.8} />
            </View>
            <Text style={styles.emptyTitle}>{t("sahayak.empty")}</Text>
            <Text style={styles.emptyHint}>{t("sahayak.emptyHint")}</Text>
          </View>
        ) : (
          <FlatList
            ref={listRef}
            data={messages}
            keyExtractor={(m) => m.id}
            renderItem={renderItem}
            contentContainerStyle={styles.list}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
          />
        )}
        {busy ? (
          <View style={styles.typingRow}>
            <EyeLoader size={16} />
            <Text style={styles.typingText}>{t("sahayak.thinking")}</Text>
          </View>
        ) : null}
        <View style={styles.inputBar}>
          <TextInput
            testID="sahayak-input"
            style={styles.input}
            value={input}
            onChangeText={setInput}
            placeholder={t("sahayak.placeholder")}
            placeholderTextColor={colors.muted}
            multiline
            maxLength={2000}
          />
          <Pressable
            testID="sahayak-send"
            accessibilityRole="button"
            onPress={() => void send()}
            disabled={busy || input.trim().length === 0}
            style={[styles.sendBtn, (busy || input.trim().length === 0) && { opacity: 0.4 }]}
          >
            <Send size={22} color={colors.onPrimary} strokeWidth={2.2} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  list: { padding: sizes.screenPadding, gap: spacing.md, paddingBottom: spacing.lg },
  bubble: {
    maxWidth: "85%",
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  userBubble: {
    alignSelf: "flex-end",
    backgroundColor: colors.primary,
    borderBottomRightRadius: radius.sm,
  },
  userText: { fontFamily: fonts.medium, fontSize: type.base, color: colors.onPrimary },
  botBubble: {
    alignSelf: "flex-start",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderBottomLeftRadius: radius.sm,
  },
  errorBubble: { borderColor: colors.danger },
  botText: { fontFamily: fonts.regular, fontSize: type.base, color: colors.text, lineHeight: 24 },
  citeRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  citeChip: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 3,
    maxWidth: 220,
  },
  citeText: { fontFamily: fonts.semiBold, fontSize: 11, color: colors.primary },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm, padding: spacing.xl },
  emptyIcon: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  emptyTitle: { fontFamily: fonts.bold, fontSize: type.lg, color: colors.text, textAlign: "center" },
  emptyHint: { fontFamily: fonts.regular, fontSize: type.base, color: colors.muted, textAlign: "center" },
  typingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: sizes.screenPadding,
    paddingBottom: spacing.xs,
  },
  typingText: { fontFamily: fonts.medium, fontSize: type.sm, color: colors.muted },
  inputBar: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: spacing.sm,
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  input: {
    flex: 1,
    minHeight: 48,
    maxHeight: 120,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.background,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
  },
  sendBtn: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
});
