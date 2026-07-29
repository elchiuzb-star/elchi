import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { T, type Lang, type TKey } from "./translations";

export type { Lang, TKey };

type I18nContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  /** Translate a key for the active language, falling back to en, then the key. */
  t: (k: TKey) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({
  children,
  initialLang = "uz",
}: {
  children: ReactNode;
  initialLang?: Lang;
}) {
  const [lang, setLang] = useState<Lang>(initialLang);

  const t = useCallback(
    (k: TKey): string => {
      const dict = T[lang] as Record<string, unknown>;
      const v = dict[k as string];
      if (typeof v === "string") return v;
      const en = (T.en as Record<string, unknown>)[k as string];
      return typeof en === "string" ? en : String(k);
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useT(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useT must be used within <I18nProvider>");
  return ctx;
}
