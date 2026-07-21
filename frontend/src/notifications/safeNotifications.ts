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
  requestPermissionsAsync: () => Promise<{ status?: string }>;
  getExpoPushTokenAsync: (opts?: { projectId?: string }) => Promise<{ data: string }>;
  setNotificationChannelAsync?: (id: string, channel: Record<string, unknown>) => Promise<unknown>;
  setNotificationHandler?: (handler: Record<string, unknown>) => void;
  addNotificationResponseReceivedListener?: (
    cb: (resp: {
      notification?: { request?: { content?: { data?: Record<string, unknown> } } };
    }) => void,
  ) => { remove: () => void };
  AndroidImportance?: Record<string, number>;
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

/**
 * Prompt 17 Part E: register for Expo push. Returns the ExponentPushToken or
 * null. Only yields a token on real dev/production builds — Expo Go (iOS AND
 * Android on SDK 53+) has no remote-push module, so this safely no-ops there.
 */
export async function registerPushTokenSafe(): Promise<string | null> {
  const mod = getNotificationsModule();
  if (!mod) return null;
  try {
    const perm = await mod.requestPermissionsAsync();
    if (perm?.status && perm.status !== "granted") return null;
    if (Platform.OS === "android" && mod.setNotificationChannelAsync) {
      await mod.setNotificationChannelAsync("default", {
        name: "HogoPlus",
        importance: mod.AndroidImportance?.HIGH ?? 4,
        sound: "default",
      });
    }
    const projectId =
      (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas
        ?.projectId ?? (Constants as unknown as { easConfig?: { projectId?: string } }).easConfig?.projectId;
    const token = await mod.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
    return token?.data ?? null;
  } catch {
    return null; // push unavailable — in-app notifications remain the source of truth
  }
}

/** Show foreground pushes as banners (built apps only; no-op elsewhere). */
export function configureForegroundNotificationsSafe(): void {
  const mod = getNotificationsModule();
  if (!mod?.setNotificationHandler) return;
  try {
    mod.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowBanner: true,
        shouldShowList: true,
        shouldPlaySound: false,
        shouldSetBadge: false,
      }),
    });
  } catch {
    // ignore
  }
}

/** Tap-on-push → callback with the notification's data payload. Returns cleanup. */
export function addNotificationTapListener(
  cb: (data: Record<string, unknown>) => void,
): () => void {
  const mod = getNotificationsModule();
  if (!mod?.addNotificationResponseReceivedListener) return () => undefined;
  try {
    const sub = mod.addNotificationResponseReceivedListener((resp) => {
      cb(resp?.notification?.request?.content?.data ?? {});
    });
    return () => sub.remove();
  } catch {
    return () => undefined;
  }
}
