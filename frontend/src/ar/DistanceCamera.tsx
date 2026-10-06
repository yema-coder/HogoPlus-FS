// DistanceCamera: renders the native AR preview when available (live object
// distance), otherwise the plain expo-camera CameraView (Expo Go / web /
// non-AR devices). Exposes the SAME imperative API expo-camera's ref has, so the
// capture screens barely change. The capture→submit flow never depends on AR.

import { useIsFocused } from "@react-navigation/native";
import { CameraView } from "expo-camera";
import React, {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { AppState, StyleProp, StyleSheet, View, ViewStyle } from "react-native";

import {
  captureStill,
  getArCapabilities,
  getArDistanceViewManager,
  isArModulePresent,
  onDistanceUpdate,
  onStatusUpdate,
  pauseSession,
  resumeSession,
  setTarget as setNativeTarget,
  setTorch as setNativeTorch,
  startSession,
  stopSession,
} from "./arDistance";
import { applyCalibration, getCalibrationSync, loadCalibration } from "./calibration";
import { evaluateDistance } from "./distanceFilter";
import type { ArCapabilities, CaptureDistanceMeta, DistanceReading, DistanceSample } from "./types";

const WINDOW_MS = 500;
// BUG 1: if the AR GL preview produces no frame/status within this window we treat
// it as hung (black screen) or crashed and fall back to the plain camera for good.
const AR_READY_TIMEOUT_MS = 5000;

export interface DistancePhoto {
  uri: string;
  width: number;
  height: number;
  distance?: DistanceReading & { intrinsics?: unknown };
  distanceMeta?: unknown; // raw CaptureResult.distance (for the payload)
  intrinsics?: unknown;
}

export interface DistanceCameraRef {
  takePictureAsync: (opts?: { quality?: number }) => Promise<DistancePhoto | null>;
  recordAsync: (opts?: { maxDuration?: number }) => Promise<{ uri: string } | null>;
  stopRecording: () => void;
  setTarget: (xFrac: number, yFrac: number) => void;
  getLastReading: () => DistanceReading | null;
  isAr: () => boolean;
}

interface Props {
  mode: "picture" | "video";
  facing?: "back" | "front";
  videoQuality?: "720p" | "1080p" | "480p";
  videoBitrate?: number;
  enableTorch?: boolean;
  active?: boolean; // pause the AR session when the screen loses focus
  style?: StyleProp<ViewStyle>;
  onReading?: (r: DistanceReading) => void;
  onCapabilities?: (c: ArCapabilities) => void;
}

export const DistanceCamera = forwardRef<DistanceCameraRef, Props>(function DistanceCamera(
  { mode, facing = "back", videoQuality = "720p", videoBitrate, enableTorch, active = true, style, onReading, onCapabilities },
  ref,
) {
  const camRef = useRef<CameraView>(null);
  const windowRef = useRef<DistanceSample[]>([]);
  const lastReadingRef = useRef<DistanceReading | null>(null);
  const [caps, setCaps] = useState<ArCapabilities | null>(null);
  // BUG 1: mount the plain camera first; promote to AR only when supported, and if
  // the AR preview never signals liveness within AR_READY_TIMEOUT_MS fall back to
  // the plain camera permanently (prevents the 10-15s black-screen hang / crash).
  const [arTimedOut, setArTimedOut] = useState(false);
  const arLiveRef = useRef(false);

  // run the camera ONLY while the screen is focused AND the app is foregrounded
  const isFocused = useIsFocused();
  const [appActive, setAppActive] = useState(AppState.currentState === "active");
  const effectiveActive = active && isFocused && appActive;

  // AR is only used for still photos; video always uses the plain camera.
  const ArView = useMemo(() => getArDistanceViewManager() as React.ComponentType<{ style?: StyleProp<ViewStyle> }> | null, []);
  const wantAr = isArModulePresent() && !!ArView && mode === "picture" && caps?.supported !== false;
  const useAr = wantAr && caps?.supported === true && !arTimedOut;

  // track app foreground/background to pause/release the camera off-screen
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => setAppActive(s === "active"));
    return () => sub.remove();
  }, []);

  // runtime capability check each mount (RULE 5)
  useEffect(() => {
    let alive = true;
    void loadCalibration(); // admin tape-measure correction (A3), applied below
    void getArCapabilities().then((c) => {
      if (!alive) return;
      setCaps(c);
      onCapabilities?.(c);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // AR session lifecycle + live distance subscription
  useEffect(() => {
    if (!useAr) return;
    arLiveRef.current = false;
    void startSession();
    // liveness: onDistance (~10 Hz once frames flow) or onStatus (init / failure)
    // both prove the native session is alive and rendering — cancels the watchdog.
    const markLive = () => {
      arLiveRef.current = true;
    };
    const offStatus = onStatusUpdate(markLive);
    const off = onDistanceUpdate((u) => {
      markLive();
      const now = Date.now();
      if (u.distanceM != null) windowRef.current.push({ value: u.distanceM, timestamp: now });
      windowRef.current = windowRef.current.filter((s) => now - s.timestamp <= WINDOW_MS);
      const reading = applyCalibration(
        evaluateDistance({
          samples: windowRef.current,
          now,
          method: u.method,
          trackingState: u.trackingState,
          windowMs: WINDOW_MS,
          hint: u.hint,
        }),
      );
      // debug HUD reprojection dot: carry the native back-projected sampled point
      reading.projX = u.projX;
      reading.projY = u.projY;
      lastReadingRef.current = reading;
      onReading?.(reading);
    });
    // watchdog: no liveness within the timeout → the AR preview is hung/crashed,
    // fall back to the plain camera for the rest of this screen.
    const watchdog = setTimeout(() => {
      if (!arLiveRef.current) setArTimedOut(true);
    }, AR_READY_TIMEOUT_MS);
    return () => {
      clearTimeout(watchdog);
      off();
      offStatus();
      void stopSession();
      windowRef.current = [];
      lastReadingRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useAr]);

  // pause/resume with screen focus + app state (never run AR off-screen/background)
  useEffect(() => {
    if (!useAr) return;
    if (effectiveActive) void resumeSession();
    else void pauseSession();
  }, [effectiveActive, useAr]);

  // torch: native toggle for AR, prop for the plain camera
  useEffect(() => {
    if (useAr) void setNativeTorch(!!enableTorch);
  }, [enableTorch, useAr]);

  useImperativeHandle(ref, () => ({
    isAr: () => useAr,
    getLastReading: () => lastReadingRef.current,
    setTarget: (x, y) => {
      if (useAr) void setNativeTarget(x, y);
    },
    takePictureAsync: async (opts) => {
      if (useAr) {
        const res = await captureStill();
        if (res.uri) {
          // apply the admin calibration to the persisted measurement too (A3)
          const cal = getCalibrationSync();
          const meta = res.distance as CaptureDistanceMeta;
          if (cal.scale !== 1 && meta?.distance_m != null) {
            meta.distance_m = Math.round(meta.distance_m * cal.scale * 100) / 100;
            if (meta.sample_spread_m != null) {
              meta.sample_spread_m = Math.round(meta.sample_spread_m * cal.scale * 100) / 100;
            }
          }
          return {
            uri: res.uri,
            width: res.width || 1200,
            height: res.height || 1600,
            distanceMeta: meta,
            intrinsics: res.intrinsics,
          };
        }
        // AR capture failed — nothing to fall back to (AR owns the camera)
        return null;
      }
      const photo = await camRef.current?.takePictureAsync({ quality: opts?.quality ?? 0.85 });
      if (!photo?.uri) return null;
      return { uri: photo.uri, width: photo.width || 1200, height: photo.height || 1600 };
    },
    recordAsync: async (opts) => {
      const v = await camRef.current?.recordAsync({ maxDuration: opts?.maxDuration ?? 30 });
      return v?.uri ? { uri: v.uri } : null;
    },
    stopRecording: () => camRef.current?.stopRecording(),
  }));

  if (useAr && ArView) {
    return (
      <View style={[styles.fill, style]}>
        <ArView style={StyleSheet.absoluteFill} />
      </View>
    );
  }

  return (
    <CameraView
      ref={camRef}
      style={[styles.fill, style]}
      facing={facing}
      mode={mode}
      active={effectiveActive}
      enableTorch={!!enableTorch}
      videoQuality={videoQuality}
      videoBitrate={videoBitrate}
    />
  );
});

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: "#000000" },
});
