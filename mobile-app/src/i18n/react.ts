/**
 * React bindings for the dictionary.
 *
 * `useSyncExternalStore` rather than a context provider: the locale is a single module-level value, every
 * screen reads it, and nothing needs to override it for a subtree. A provider would add a wrapper around the
 * whole app to express something that has exactly one source.
 */
import { useCallback, useSyncExternalStore } from "react";

import { getLocale, setLocale, subscribe, translate, type Locale, type MessageKey } from "./index";

/** The active locale, re-rendering the caller when it changes. */
export function useLocale(): [Locale, (next: Locale) => void] {
  const locale = useSyncExternalStore(subscribe, getLocale, () => getLocale());
  return [locale, setLocale];
}

/**
 * The translator, bound to the active locale.
 *
 * The returned function is recreated when the language changes, which is what makes a screen re-render into
 * the other language instead of keeping the strings it rendered with.
 */
export function useT(): (key: MessageKey, values?: Record<string, string | number>) => string {
  const locale = useSyncExternalStore(subscribe, getLocale, () => getLocale());
  return useCallback((key: MessageKey, values?: Record<string, string | number>) => translate(key, values), [locale]);
}
