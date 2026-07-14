import React from "react";
import { Modal, StyleSheet, Text, View } from "react-native";
import { useTranslation } from "react-i18next";

import { BigButton } from "@/src/components/BigButton";
import { colors, fonts, radius, spacing, type } from "@/src/theme/tokens";

interface Props {
  visible: boolean;
  title: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  testIDPrefix: string;
}

/** Cross-platform confirm dialog (RN Alert is unavailable on web). */
export function ConfirmModal({
  visible,
  title,
  confirmLabel,
  danger = false,
  onConfirm,
  onCancel,
  testIDPrefix,
}: Props) {
  const { t } = useTranslation();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={styles.card} testID={`${testIDPrefix}-confirm-modal`}>
          <Text style={styles.title}>{title}</Text>
          <View style={styles.row}>
            <BigButton
              testID={`${testIDPrefix}-cancel-button`}
              label={t("common.cancel")}
              variant="muted"
              onPress={onCancel}
              style={styles.btn}
            />
            <BigButton
              testID={`${testIDPrefix}-confirm-button`}
              label={confirmLabel ?? t("common.confirm")}
              variant={danger ? "danger" : "primary"}
              onPress={onConfirm}
              style={styles.btn}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    padding: spacing.xl,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.xl,
  },
  title: {
    fontFamily: fonts.semiBold,
    fontSize: type.lg,
    color: colors.text,
    textAlign: "center",
  },
  row: { flexDirection: "row", gap: spacing.md },
  btn: { flex: 1 },
});
