const { withInfoPlist, withAndroidManifest, AndroidConfig } = require("expo/config-plugins");

// Config plugin for the local expo-ar-distance module. Ensures the camera usage
// string (iOS) and ARCore "optional" metadata + non-required AR feature (Android)
// are present in the app manifest after prebuild. ARCore is OPTIONAL so the app
// still installs and runs (plain-camera Tier 4) on non-AR devices.
const withArDistance = (config) => {
  config = withInfoPlist(config, (c) => {
    if (!c.modResults.NSCameraUsageDescription) {
      c.modResults.NSCameraUsageDescription = "Measure distance and capture incident photos";
    }
    return c;
  });

  config = withAndroidManifest(config, (c) => {
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(c.modResults);
    AndroidConfig.Manifest.addMetaDataItemToMainApplication(app, "com.google.ar.core", "optional");

    const manifest = c.modResults.manifest;
    manifest["uses-feature"] = manifest["uses-feature"] || [];
    const hasArFeature = manifest["uses-feature"].some(
      (f) => f.$ && f.$["android:name"] === "android.hardware.camera.ar",
    );
    if (!hasArFeature) {
      manifest["uses-feature"].push({
        $: { "android:name": "android.hardware.camera.ar", "android:required": "false" },
      });
    }
    return c;
  });

  return config;
};

module.exports = withArDistance;
