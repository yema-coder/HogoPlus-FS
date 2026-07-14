import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { LogBox } from "react-native";
import { useFonts } from "expo-font";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import "@/src/i18n";
import { ToastHost } from "@/src/components/Toast";
import { useOutboxStore } from "@/src/offline/outbox";
import { useAuthStore } from "@/src/stores/authStore";
import { colors } from "@/src/theme/tokens";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

// Keep the native splash visible from cold start until icon fonts register.
// Required because @expo/vector-icons' componentDidMount fallback fires
// Font.loadAsync against a broken vendor path if any <Icon> mounts before
// the family is registered — which throws on Android Expo Go.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [iconsLoaded, iconsError] = useIconFonts();
  const [fontsLoaded, fontsError] = useFonts({
    "Baloo2-Regular": require("../assets/fonts/Baloo2-Regular.ttf"),
    "Baloo2-Medium": require("../assets/fonts/Baloo2-Medium.ttf"),
    "Baloo2-SemiBold": require("../assets/fonts/Baloo2-SemiBold.ttf"),
    "Baloo2-Bold": require("../assets/fonts/Baloo2-Bold.ttf"),
  });
  const status = useAuthStore((s) => s.status);
  const hydrate = useAuthStore((s) => s.hydrate);
  const initOutbox = useOutboxStore((s) => s.init);
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    void hydrate();
    void initOutbox();
  }, [hydrate, initOutbox]);

  useEffect(() => {
    if ((iconsLoaded || iconsError) && (fontsLoaded || fontsError)) {
      SplashScreen.hideAsync();
    }
  }, [iconsLoaded, iconsError, fontsLoaded, fontsError]);

  // Clean logout: whenever the session dies, land on phone entry.
  useEffect(() => {
    if (status === "unauthenticated" && segments[0] !== "(auth)" && segments.length > 0) {
      router.replace("/(auth)/phone");
    }
  }, [status, segments, router]);

  // If the CDN is unreachable we fall through on error rather than wedging
  // the app — icons will tofu, but the app still boots.
  if ((!iconsLoaded && !iconsError) || (!fontsLoaded && !fontsError)) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: colors.background },
          }}
        />
        <ToastHost />
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
