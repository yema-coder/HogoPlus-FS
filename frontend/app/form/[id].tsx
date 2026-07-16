import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useTranslation } from "react-i18next";

import { listForms } from "@/src/api/endpoints";
import type { FormDefinitionItem } from "@/src/api/types";
import { ErrorRetry } from "@/src/components/ErrorRetry";
import { EyeLoader } from "@/src/components/EyeLoader";
import { ScreenHeader } from "@/src/components/ScreenHeader";
import { FormRenderer } from "@/src/forms/FormRenderer";
import { useCachedFetch } from "@/src/hooks/useCachedFetch";
import { tri } from "@/src/i18n";
import { useAuthStore } from "@/src/stores/authStore";
import { colors } from "@/src/theme/tokens";

export default function FormFillScreen() {
  const router = useRouter();
  const { t } = useTranslation();
  const { id } = useLocalSearchParams<{ id: string }>();
  const profile = useAuthStore((s) => s.profile);
  const dept = profile?.department_code ?? "";
  const { data, error, refresh } = useCachedFetch<FormDefinitionItem[]>(
    `forms-${dept}`,
    () => listForms(),
  );

  const definition = data?.find((f) => f.id === id) ?? null;

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]} testID="form-fill-screen">
      <ScreenHeader title={definition ? tri(definition as unknown as Record<string, unknown>, "title") : t("forms.title")} />
      {error && !data ? (
        <ErrorRetry onRetry={() => void refresh()} />
      ) : !definition ? (
        <View style={styles.loading}>
          <EyeLoader size={40} />
        </View>
      ) : (
        <FormRenderer
          definition={definition}
          onSubmitted={(queued, rid) =>
            router.replace({
              pathname: "/form/success",
              params: { queued: queued ? "1" : "0", rid: rid ?? "" },
            })
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  loading: { flex: 1, alignItems: "center", justifyContent: "center" },
});
