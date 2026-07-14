import { Minus, Plus } from "lucide-react-native";
import React, { useEffect, useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import type { FormFieldDef } from "@/src/api/types";
import { colors, fonts, radius, sizes, type } from "@/src/theme/tokens";

interface Props {
  field: FormFieldDef;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  error?: boolean;
  testID: string;
}

export function NumberFieldInput({ field, value, onChange, error, testID }: Props) {
  const [text, setText] = useState(value !== undefined ? String(value) : "");
  const min = field.validation?.min;
  const max = field.validation?.max;
  const hasSteppers = min !== undefined || max !== undefined;

  useEffect(() => {
    // external change (draft resume / steppers)
    if (value === undefined && text !== "") return;
    if (value !== undefined && Number(text) !== value) setText(String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const commit = (raw: string) => {
    setText(raw);
    const cleaned = raw.replace(/[^0-9.-]/g, "");
    if (cleaned === "" || cleaned === "-" || cleaned === ".") {
      onChange(undefined);
      return;
    }
    const n = Number(cleaned);
    if (!Number.isNaN(n)) onChange(n);
  };

  const step = (delta: number) => {
    let n = (value ?? (min !== undefined ? min : 0)) + delta;
    if (min !== undefined && n < min) n = min;
    if (max !== undefined && n > max) n = max;
    onChange(n);
    setText(String(n));
  };

  return (
    <View style={styles.row}>
      {hasSteppers ? (
        <Pressable testID={`${testID}-minus`} onPress={() => step(-1)} style={styles.stepBtn}>
          <Minus size={26} color={colors.text} strokeWidth={2.6} />
        </Pressable>
      ) : null}
      <TextInput
        testID={testID}
        style={[styles.input, hasSteppers && styles.inputCenter, error && styles.inputError]}
        value={text}
        onChangeText={commit}
        keyboardType="numeric"
        inputMode="decimal"
        maxLength={12}
        placeholderTextColor={colors.muted}
      />
      {hasSteppers ? (
        <Pressable testID={`${testID}-plus`} onPress={() => step(1)} style={styles.stepBtn}>
          <Plus size={26} color={colors.text} strokeWidth={2.6} />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  stepBtn: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  input: {
    flex: 1,
    minHeight: sizes.touchTarget,
    borderRadius: radius.md,
    borderWidth: 2,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: 16,
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
  },
  inputCenter: { textAlign: "center" },
  inputError: { borderColor: colors.danger },
});
