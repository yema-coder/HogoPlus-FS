import { storage } from "@/src/utils/storage";

const draftKey = (defId: string) => `hogo.draft.${defId}`;

export async function loadDraft(defId: string): Promise<Record<string, unknown> | null> {
  const raw = await storage.getItem<string>(draftKey(defId), "");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export async function saveDraft(defId: string, values: Record<string, unknown>): Promise<void> {
  await storage.setItem(draftKey(defId), JSON.stringify(values));
}

export async function clearDraft(defId: string): Promise<void> {
  await storage.removeItem(draftKey(defId));
}

/** Local (not-yet-uploaded) file URI vs a server file key. */
export function isLocalUri(v: string): boolean {
  return (
    v.startsWith("file:") || v.startsWith("blob:") || v.startsWith("data:") || v.startsWith("/")
  );
}
