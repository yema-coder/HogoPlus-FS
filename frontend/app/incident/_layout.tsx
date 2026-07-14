import { Stack } from "expo-router";
import React from "react";

import { colors } from "@/src/theme/tokens";

export default function IncidentLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
