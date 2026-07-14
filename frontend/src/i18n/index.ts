import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import hi from "./locales/hi.json";
import mr from "./locales/mr.json";

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    hi: { translation: hi },
    mr: { translation: mr },
  },
  lng: "mr",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

export default i18n;

export type AppLanguage = "en" | "hi" | "mr";

export const LANGUAGES: { code: AppLanguage; native: string }[] = [
  { code: "mr", native: "मराठी" },
  { code: "hi", native: "हिंदी" },
  { code: "en", native: "English" },
];

/** Pick the trilingual field matching current language, e.g. name_en/name_hi/name_mr */
export function tri(obj: Record<string, unknown> | null | undefined, base: string): string {
  if (!obj) return "";
  const lang = (i18n.language || "mr").slice(0, 2);
  const val = obj[`${base}_${lang}`] ?? obj[`${base}_en`];
  return typeof val === "string" ? val : "";
}
