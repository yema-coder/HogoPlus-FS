// v1.0.15 PIPELINE-PROOF FIX for the neverForLocation flag on BLUETOOTH_SCAN.
//
// ROOT CAUSE (v1.0.14 artifact autopsy): react-native-ble-plx's LIBRARY
// AndroidManifest.xml (node_modules/react-native-ble-plx/android/src/main/AndroidManifest.xml)
// declares:
//   <uses-permission android:name="android.permission.BLUETOOTH_SCAN"
//                    android:usesPermissionFlags="neverForLocation" tools:targetApi="s" />
// The Gradle MANIFEST MERGER folds every library manifest into the final APK manifest
// AFTER `expo prebuild`, so a clean app.json / clean generated app manifest is not
// enough — the merger re-contributes the flag from the library AAR on every build
// (shipped artifact showed usesPermissionFlags="0x00010000" = FLAG_NEVER_FOR_LOCATION).
// With that flag the OS strips all iBeacon advertisement frames before the app sees
// them, killing beacon detection fleet-wide.
//
// THE FIX operates at MERGE TIME — the last authority in ANY Gradle build:
// we stamp tools:remove="android:usesPermissionFlags" onto the app manifest's
// BLUETOOTH_SCAN <uses-permission> element. The Android manifest merger is
// contractually required to strip that attribute from the merged output regardless
// of which library contributes it. Because this is an Expo config plugin listed in
// app.json's plugins array, every prebuild the pipeline runs re-applies the stamp:
// regenerating/overriding the native project cannot lose it (prebuild always executes
// the plugins to generate that project), and no library manifest can override a
// tools:remove directive during the merge.
const { withAndroidManifest } = require("expo/config-plugins");

const SCAN = "android.permission.BLUETOOTH_SCAN";

module.exports = function withBleScanNoNeverForLocation(config) {
  return withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults.manifest;
    manifest.$ = manifest.$ || {};
    manifest.$["xmlns:tools"] = "http://schemas.android.com/tools";
    if (!Array.isArray(manifest["uses-permission"])) manifest["uses-permission"] = [];
    const perms = manifest["uses-permission"];
    let scan = perms.find((p) => p.$ && p.$["android:name"] === SCAN);
    if (!scan) {
      scan = { $: { "android:name": SCAN } };
      perms.push(scan);
    }
    delete scan.$["android:usesPermissionFlags"];
    scan.$["tools:remove"] = "android:usesPermissionFlags";
    return cfg;
  });
};
