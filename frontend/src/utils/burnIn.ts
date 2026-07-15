import * as ImageManipulator from "expo-image-manipulator";
import type React from "react";
import { Platform, View } from "react-native";
import { captureRef } from "react-native-view-shot";

const MAX_DIM = 1600;

/**
 * Burns the watermark overlay into pixels (view-shot of the composited view)
 * and compresses to ~300-500 KB (max dimension 1600px, quality 0.7).
 * On web (no view-shot) falls back to the raw photo, resized + compressed.
 * Shared by the incident flow and the form-engine photo fields.
 */
export async function burnInAndCompress(
  ref: React.RefObject<View | null>,
  shotUri: string,
  shotW: number,
  shotH: number,
): Promise<string> {
  const landscape = shotW >= shotH;
  const maxSide = Math.min(MAX_DIM, Math.max(shotW, shotH));
  const targetW = landscape ? maxSide : Math.round((maxSide * shotW) / shotH);
  const targetH = landscape ? Math.round((maxSide * shotH) / shotW) : maxSide;

  if (Platform.OS !== "web" && ref.current) {
    try {
      const burned = await captureRef(ref, {
        format: "jpg",
        quality: 0.9,
        width: targetW,
        height: targetH,
        result: "tmpfile",
      });
      const out = await ImageManipulator.manipulateAsync(burned, [], {
        compress: 0.7,
        format: ImageManipulator.SaveFormat.JPEG,
      });
      return out.uri;
    } catch {
      // fall through to the raw photo
    }
  }
  const out = await ImageManipulator.manipulateAsync(
    shotUri,
    [{ resize: landscape ? { width: targetW } : { height: targetH } }],
    { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG },
  );
  return out.uri;
}

/** Never-throwing variant: worst case returns the raw camera photo untouched. */
export async function burnInSafe(
  ref: React.RefObject<View | null>,
  shotUri: string,
  shotW: number,
  shotH: number,
): Promise<string> {
  try {
    return await burnInAndCompress(ref, shotUri, shotW, shotH);
  } catch (e) {
    console.warn("burnIn failed, submitting raw photo:", e);
    return shotUri;
  }
}
