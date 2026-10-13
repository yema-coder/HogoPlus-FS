import * as Application from "expo-application";
import Constants from "expo-constants";

/**
 * TRUE installed build identity — read from the NATIVE build, not the JS bundle.
 *
 * `Constants.expoConfig.version` is only the value baked into the JS bundle at build
 * time; the Publish pipeline can stamp a different versionName/versionCode into the
 * actual artifact, so that value cannot be trusted as "the app's version".
 * `expo-application` reads the real installed values (Android versionName /
 * versionCode, iOS CFBundleShortVersionString / build number). We fall back to the
 * bundle value only on web / Expo Go, where the native module is absent.
 */
export const APP_VERSION: string =
  Application.nativeApplicationVersion ?? Constants.expoConfig?.version ?? "0.0.0";

/** Android versionCode / iOS build number — the integer Google Play actually compares. */
export const APP_BUILD: string | null = Application.nativeBuildVersion ?? null;

/** e.g. "1.0.27 (10027)", or just "1.0.27" when the build number is unavailable. */
export const APP_VERSION_LABEL: string = APP_BUILD ? `${APP_VERSION} (${APP_BUILD})` : APP_VERSION;
