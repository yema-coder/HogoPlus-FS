// JS bridge to the custom native `ExpoArDistance` module (PART 1). SAFE in Expo
// Go / web / unsupported devices: the native module simply isn't registered there,
// so every access is guarded and degrades to "no AR" (plain camera fallback).
//
// The native module owns a single ARKit/ARCore session (there is only one camera),
// emits throttled `onDistance` updates (~10 Hz) and exposes imperative async funcs.

import { Platform } from "react-native";

import { parseArUpdate, parseCapabilities, parseCaptureResult } from "./parseCaptureResult";
import type { ArCapabilities, CaptureResult, RawArUpdate } from "./types";

type NativeModuleLike = {
  addListener: (event: string, cb: (payload: unknown) => void) => { remove: () => void };
  getCapabilitiesAsync?: () => Promise<unknown>;
  startAsync?: () => Promise<void>;
  stopAsync?: () => Promise<void>;
  pauseAsync?: () => Promise<void>;
  resumeAsync?: () => Promise<void>;
  setTargetAsync?: (x: number, y: number) => Promise<void>;
  setTorchAsync?: (on: boolean) => Promise<void>;
  captureAsync?: () => Promise<unknown>;
};

let _module: NativeModuleLike | null | undefined;

function getModule(): NativeModuleLike | null {
  if (_module !== undefined) return _module;
  if (Platform.OS === "web") {
    _module = null;
    return null;
  }
  try {
    // require lazily so web/Expo-Go never evaluate native-only code at import time
    const { requireNativeModule } = require("expo-modules-core");
    _module = requireNativeModule("ExpoArDistance") as NativeModuleLike;
  } catch {
    _module = null; // not present in this runtime (Expo Go, unsupported build)
  }
  return _module;
}

/** The native view manager, or null when AR is unavailable. */
export function getArDistanceViewManager(): unknown | null {
  if (Platform.OS === "web") return null;
  try {
    const { requireNativeViewManager } = require("expo-modules-core");
    return requireNativeViewManager("ExpoArDistance");
  } catch {
    return null;
  }
}

/** Is the native AR module present at all (needed before rendering the AR view). */
export function isArModulePresent(): boolean {
  return !!getModule();
}

/** Runtime capability + permission check — call every time the camera opens. */
export async function getArCapabilities(): Promise<ArCapabilities> {
  const m = getModule();
  if (!m || !m.getCapabilitiesAsync) {
    return { supported: false, hasHardwareDepth: false, reason: "no_native" };
  }
  try {
    return parseCapabilities(await m.getCapabilitiesAsync());
  } catch {
    return { supported: false, hasHardwareDepth: false, reason: "error" };
  }
}

/** Subscribe to throttled live distance updates. Returns an unsubscribe fn. */
export function onDistanceUpdate(cb: (u: ReturnType<typeof parseArUpdate>) => void): () => void {
  const m = getModule();
  if (!m) return () => undefined;
  const sub = m.addListener("onDistance", (payload) => cb(parseArUpdate(payload as RawArUpdate)));
  return () => sub.remove();
}

export function onStatusUpdate(cb: (payload: unknown) => void): () => void {
  const m = getModule();
  if (!m) return () => undefined;
  const sub = m.addListener("onStatus", cb);
  return () => sub.remove();
}

export async function startSession(): Promise<void> {
  await getModule()?.startAsync?.().catch(() => undefined);
}
export async function stopSession(): Promise<void> {
  await getModule()?.stopAsync?.().catch(() => undefined);
}
export async function pauseSession(): Promise<void> {
  await getModule()?.pauseAsync?.().catch(() => undefined);
}
export async function resumeSession(): Promise<void> {
  await getModule()?.resumeAsync?.().catch(() => undefined);
}
/** Measure at a tap point expressed as fractions (0..1) of the preview frame. */
export async function setTarget(xFrac: number, yFrac: number): Promise<void> {
  await getModule()?.setTargetAsync?.(xFrac, yFrac).catch(() => undefined);
}
export async function setTorch(on: boolean): Promise<void> {
  await getModule()?.setTorchAsync?.(on).catch(() => undefined);
}

/** Capture a full-resolution still with distance metadata. Never throws; returns
 * a result with uri="" on failure so the caller can fall back to the plain camera. */
export async function captureStill(): Promise<CaptureResult> {
  const m = getModule();
  if (!m || !m.captureAsync) return parseCaptureResult(null);
  try {
    return parseCaptureResult(await m.captureAsync());
  } catch {
    return parseCaptureResult(null);
  }
}
