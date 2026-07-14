import * as Haptics from "expo-haptics";
import React, { useEffect, useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { useTranslation } from "react-i18next";

import { ApiError, uploadFile } from "@/src/api/client";
import { submitForm } from "@/src/api/endpoints";
import type { FormDefinitionItem, FormFieldDef } from "@/src/api/types";
import { BigButton } from "@/src/components/BigButton";
import { showToast } from "@/src/components/Toast";
import { FieldWrapper } from "@/src/forms/FieldWrapper";
import { clearDraft, isLocalUri, loadDraft, saveDraft } from "@/src/forms/draft";
import { DateTimeFieldInput } from "@/src/forms/fields/DateTimeFieldInput";
import { GpsFieldInput, type GpsValue } from "@/src/forms/fields/GpsFieldInput";
import { NumberFieldInput } from "@/src/forms/fields/NumberFieldInput";
import { PhotoFieldInput } from "@/src/forms/fields/PhotoFieldInput";
import { SelectFieldInput } from "@/src/forms/fields/SelectFieldInput";
import { TextFieldInput } from "@/src/forms/fields/TextFieldInput";
import { ToggleFieldInput } from "@/src/forms/fields/ToggleFieldInput";
import { VoiceFieldInput } from "@/src/forms/fields/VoiceFieldInput";
import { tri } from "@/src/i18n";
import { useOutboxStore, type OutboxFile } from "@/src/offline/outbox";
import { sizes, spacing } from "@/src/theme/tokens";

interface Props {
  definition: FormDefinitionItem;
  onSubmitted: (queued: boolean, id?: string) => void;
}

const isEmpty = (v: unknown) =>
  v === undefined || v === null || (typeof v === "string" && v.trim() === "");

/** Schema-driven native form: validation, draft autosave, offline outbox. */
export function FormRenderer({ definition, onSubmitted }: Props) {
  const { t } = useTranslation();
  const enqueue = useOutboxStore((s) => s.enqueue);
  const fields = definition.schema_json.fields;

  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [draftLoaded, setDraftLoaded] = useState(false);
  const scrollRef = useRef<ScrollView>(null);
  const positions = useRef<Record<string, number>>({});
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    void (async () => {
      const draft = await loadDraft(definition.id);
      const base: Record<string, unknown> = {};
      for (const f of fields) if (f.type === "toggle") base[f.key] = false;
      if (draft && Object.keys(draft).length > 0) {
        setValues({ ...base, ...draft });
        showToast(t("forms.draftResumed"), "info");
      } else {
        setValues(base);
      }
      setDraftLoaded(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [definition.id]);

  useEffect(() => {
    if (!draftLoaded) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void saveDraft(definition.id, values), 800);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [values, draftLoaded, definition.id]);

  const setValue = (key: string, v: unknown) => {
    setValues((prev) => ({ ...prev, [key]: v }));
    setErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const validate = (): Record<string, string> => {
    const errs: Record<string, string> = {};
    for (const f of fields) {
      const v = values[f.key];
      if (f.type === "toggle") continue; // boolean always present
      if (isEmpty(v)) {
        if (f.required) errs[f.key] = t("forms.required");
        continue;
      }
      if (f.type === "number") {
        const n = Number(v);
        const min = f.validation?.min;
        const max = f.validation?.max;
        if (min !== undefined && n < min) errs[f.key] = t("forms.min", { v: min });
        else if (max !== undefined && n > max) errs[f.key] = t("forms.max", { v: max });
      }
    }
    return errs;
  };

  const scrollToFirstError = (errs: Record<string, string>) => {
    const first = fields.find((f) => errs[f.key]);
    if (first && positions.current[first.key] !== undefined) {
      scrollRef.current?.scrollTo({ y: Math.max(0, positions.current[first.key] - 16), animated: true });
    }
  };

  const submit = async () => {
    if (submitting) return;
    const errs = validate();
    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      scrollToFirstError(errs);
      showToast(t("forms.fixErrors"), "error");
      return;
    }
    setSubmitting(true);

    // strip empty optional values; collect local files
    const data: Record<string, unknown> = {};
    const localFiles: OutboxFile[] = [];
    let gpsLat: number | null = null;
    let gpsLng: number | null = null;
    for (const f of fields) {
      const v = values[f.key];
      if (f.type !== "toggle" && isEmpty(v)) continue;
      if ((f.type === "photo" || f.type === "voice_note") && typeof v === "string" && isLocalUri(v)) {
        localFiles.push({
          field: f.key,
          uri: v,
          name: f.type === "photo" ? `${f.key}.jpg` : `${f.key}.m4a`,
          kind: f.type === "photo" ? "photo" : "audio",
        });
      }
      if (f.type === "gps_point" && v && typeof v === "object") {
        const g = v as GpsValue;
        gpsLat = g.lat;
        gpsLng = g.lng;
        data[f.key] = { lat: g.lat, lng: g.lng };
        continue;
      }
      data[f.key] = v;
    }

    try {
      const photoKeys: string[] = [];
      for (const file of localFiles) {
        const uploaded = await uploadFile(file.uri, file.name);
        data[file.field] = uploaded.key;
        if (file.kind === "photo") photoKeys.push(uploaded.key);
      }
      const res = await submitForm(definition.id, {
        data_json: data,
        photos: photoKeys,
        gps_lat: gpsLat,
        gps_lng: gpsLng,
      });
      await clearDraft(definition.id);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
      onSubmitted(false, res.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        // offline: strip local file values from data (outbox re-uploads them)
        const queuedData = { ...data };
        for (const file of localFiles) delete queuedData[file.field];
        await enqueue({
          type: "form",
          payload: { definition_id: definition.id, data_json: queuedData, gps_lat: gpsLat, gps_lng: gpsLng },
          photoUri: null,
          photoName: "",
          photoField: "",
          files: localFiles,
        });
        await clearDraft(definition.id);
        onSubmitted(true);
      } else if (e instanceof ApiError && e.status === 400) {
        const detail = e.detail as { errors?: string[] } | string | null;
        const serverErrs: Record<string, string> = {};
        if (detail && typeof detail === "object" && Array.isArray(detail.errors)) {
          for (const msg of detail.errors) {
            const idx = msg.indexOf(":");
            if (idx > 0) serverErrs[msg.slice(0, idx)] = msg.slice(idx + 1).trim();
          }
        }
        if (Object.keys(serverErrs).length > 0) {
          setErrors(serverErrs);
          scrollToFirstError(serverErrs);
        }
        showToast(t("forms.fixErrors"), "error");
        setSubmitting(false);
      } else {
        showToast(t("errors.server"), "error");
        setSubmitting(false);
      }
    }
  };

  const renderInput = (f: FormFieldDef) => {
    const v = values[f.key];
    const err = Boolean(errors[f.key]);
    const testID = `input-${f.key}`;
    switch (f.type) {
      case "number":
        return (
          <NumberFieldInput
            field={f}
            value={typeof v === "number" ? v : undefined}
            onChange={(n) => setValue(f.key, n)}
            error={err}
            testID={testID}
          />
        );
      case "select":
        return (
          <SelectFieldInput
            options={f.options ?? []}
            value={typeof v === "string" ? v : undefined}
            onChange={(o) => setValue(f.key, o)}
            error={err}
            testID={testID}
          />
        );
      case "photo":
        return (
          <PhotoFieldInput
            label={tri(f as unknown as Record<string, unknown>, "label")}
            value={typeof v === "string" ? v : undefined}
            onChange={(uri) => setValue(f.key, uri)}
            error={err}
            testID={testID}
          />
        );
      case "voice_note":
        return (
          <VoiceFieldInput
            value={typeof v === "string" ? v : undefined}
            onChange={(uri) => setValue(f.key, uri)}
            error={err}
            testID={testID}
          />
        );
      case "datetime":
        return (
          <DateTimeFieldInput
            value={typeof v === "string" ? v : undefined}
            onChange={(iso) => setValue(f.key, iso)}
            error={err}
            testID={testID}
          />
        );
      case "toggle":
        return (
          <ToggleFieldInput value={Boolean(v)} onChange={(b) => setValue(f.key, b)} testID={testID} />
        );
      case "gps_point":
        return (
          <GpsFieldInput
            value={v && typeof v === "object" ? (v as GpsValue) : undefined}
            onChange={(g) => setValue(f.key, g)}
            error={err}
            testID={testID}
          />
        );
      default:
        return (
          <TextFieldInput
            value={typeof v === "string" ? v : ""}
            onChange={(txt) => setValue(f.key, txt)}
            error={err}
            testID={testID}
            multilineHint={!f.validation?.regex}
          />
        );
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
      >
        {fields.map((f) => (
          <FieldWrapper
            key={f.key}
            field={f}
            error={errors[f.key]}
            onLayout={(e) => {
              positions.current[f.key] = e.nativeEvent.layout.y;
            }}
          >
            {renderInput(f)}
          </FieldWrapper>
        ))}
        <View style={{ height: spacing.md }} />
        <BigButton
          testID="form-submit-button"
          label={t("forms.submit")}
          variant="primary"
          height={64}
          loading={submitting}
          onPress={() => void submit()}
        />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: sizes.screenPadding, paddingBottom: spacing.xxl },
});
