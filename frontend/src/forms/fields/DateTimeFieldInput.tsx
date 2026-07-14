import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import { CalendarClock } from "lucide-react-native";
import React, { useState } from "react";
import { Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useTranslation } from "react-i18next";

import { colors, fonts, radius, sizes, spacing, type } from "@/src/theme/tokens";

dayjs.extend(customParseFormat);

const DISPLAY = "DD/MM/YYYY HH:mm";

interface Props {
  value: string | undefined; // ISO string
  onChange: (v: string | undefined) => void;
  error?: boolean;
  testID: string;
}

/** Native date+time picker; DD/MM/YYYY display. Web falls back to a masked input. */
export function DateTimeFieldInput({ value, onChange, error, testID }: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"date" | "time" | null>(null);
  const [pendingDate, setPendingDate] = useState<Date | null>(null);
  const [webText, setWebText] = useState(value ? dayjs(value).format(DISPLAY) : "");
  const [webInvalid, setWebInvalid] = useState(false);

  if (Platform.OS === "web") {
    return (
      <View style={styles.wrap}>
        <TextInput
          testID={testID}
          style={[styles.input, (error || webInvalid) && styles.inputError]}
          value={webText}
          placeholder={t("forms.dateHint")}
          placeholderTextColor={colors.muted}
          onChangeText={(txt) => {
            setWebText(txt);
            if (txt.trim() === "") {
              setWebInvalid(false);
              onChange(undefined);
              return;
            }
            const parsed = dayjs(txt, DISPLAY, true);
            if (parsed.isValid()) {
              setWebInvalid(false);
              onChange(parsed.toISOString());
            } else {
              setWebInvalid(true);
            }
          }}
        />
        {webInvalid ? <Text style={styles.invalid}>{t("forms.invalidDate")}</Text> : null}
      </View>
    );
  }

  const onPicked = (event: DateTimePickerEvent, picked?: Date) => {
    if (event.type === "dismissed" || !picked) {
      setMode(null);
      setPendingDate(null);
      return;
    }
    if (mode === "date") {
      setPendingDate(picked);
      setMode("time");
      return;
    }
    // time picked: combine with pending date
    const base = pendingDate ?? new Date();
    const combined = new Date(
      base.getFullYear(),
      base.getMonth(),
      base.getDate(),
      picked.getHours(),
      picked.getMinutes(),
    );
    setMode(null);
    setPendingDate(null);
    onChange(combined.toISOString());
  };

  return (
    <View style={styles.wrap}>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        onPress={() => setMode("date")}
        style={[styles.row, error && styles.inputError]}
      >
        <CalendarClock size={24} color={value ? colors.primary : colors.muted} strokeWidth={2.2} />
        <Text style={[styles.rowText, !value && { color: colors.muted }]}>
          {value ? dayjs(value).format(DISPLAY) : t("forms.pickDateTime")}
        </Text>
      </Pressable>
      {mode ? (
        <DateTimePicker
          value={value ? new Date(value) : new Date()}
          mode={mode}
          is24Hour
          onChange={onPicked}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  row: {
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
  },
  rowText: { fontFamily: fonts.semiBold, fontSize: type.base, color: colors.text },
  input: {
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: 16,
    fontFamily: fonts.regular,
    fontSize: type.base,
    color: colors.text,
  },
  inputError: { borderColor: colors.danger },
  invalid: { fontFamily: fonts.regular, fontSize: type.sm, color: colors.danger },
});
