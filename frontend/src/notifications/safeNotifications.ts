/**
 * Safe, lazily-loaded wrapper around expo-notifications.
 *
 * Expo Go on iOS (SDK 53+) ships WITHOUT the remote-push native module — a
 * top-level `import * as Notifications from "expo-notifications"` crashes the
 * whole app at startup with "Uncaught Error: native module doesn't exist"
 * (PushNotificationIOS). Same lazy try/require guard as src/ble/BleScanner.ts:
 * if the native module is unavailable, notifications become a silent no-op and
 * the rest of the app works normally. Dev/production builds (Android included)
 * still get the real module.
 */
import Constants from "expo-constants";
import { Platform } from "react-native";

type NotificationsModule = {
  requestPermissionsAsync: () => Promise<unknown>;
};

let cached: NotificationsModule | null | undefined;

function getNotificationsModule(): NotificationsModule | null {
  if (cached !== undefined) return cached;
  const inExpoGo = Constants.appOwnership === "expo";
  // web has no push natives; Expo Go iOS is missing PushNotificationIOS entirely
  if (Platform.OS === "web" || (inExpoGo && Platform.OS === "ios")) {
    cached = null;
    return cached;
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports -- intentional lazy native import
    cached = require("expo-notifications") as NotificationsModule;
  } catch {
    // native module missing (e.g. Expo Go) — silent no-op
    cached = null;
  }
  return cached;
}

/** Request notification permission where supported; silent no-op otherwise. */
export async function requestNotificationPermissionsSafe(): Promise<void> {
  const mod = getNotificationsModule();
  if (!mod) return;
  try {
    await mod.requestPermissionsAsync();
  } catch {
    // never block the app on a notification permission error
  }
}
