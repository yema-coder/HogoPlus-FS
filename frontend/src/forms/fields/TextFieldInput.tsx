import React from "react";
import { StyleSheet, TextInput } from "react-native";

import { colors, fonts, radius, sizes, type } from "@/src/theme/tokens";

interface Props {
  value: string;
  onChange: (v: string) => void;
  error?: boolean;
  testID: string;
  multilineHint?: boolean;
}

export function TextFieldInput({ value, onChange, error, testID, multilineHint }: Props) {
  return (
    <TextInput
      testID={testID}
      style={[styles.input, multilineHint && styles.multi, error && styles.inputError]}
      value={value}
      onChangeText={onChange}
      placeholderTextColor={colors.muted}
      multiline={multilineHint}
      maxLength={500}
    />
  );
}

const styles = StyleSheet.create({
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
  multi: { minHeight: 72, textAlignVertical: "top", paddingVertical: 12 },
  inputError: { borderColor: colors.danger },
});
