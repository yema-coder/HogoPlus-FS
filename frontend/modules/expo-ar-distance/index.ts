// The app talks to this module through src/ar/arDistance.ts via
// requireNativeModule("ExpoArDistance") / requireNativeViewManager, so this entry
// only needs to exist for Expo autolinking to pick the module up at prebuild.
export const NAME = "ExpoArDistance";
