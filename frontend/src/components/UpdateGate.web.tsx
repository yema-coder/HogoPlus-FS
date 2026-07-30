/**
 * v1.0.17 — web platform stub for UpdateGate.
 * The native module `sp-react-native-in-app-updates` ships only .android.js /
 * .ios.js platform files, so importing it in the web bundle fails Metro's
 * static resolver ("Unable to resolve ./InAppUpdates"). This platform-specific
 * (.web.tsx) sibling is picked by Expo Router / Metro for web and keeps the
 * root layout crash-free. Google Play in-app updates remain wired for
 * Android/iOS bundles unchanged (see UpdateGate.tsx).
 */
export function UpdateGate() {
  return null;
}
