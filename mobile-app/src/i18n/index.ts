/**
 * Two languages, one dictionary shape.
 *
 * Uzbek is the product's language and stays the fallback: a key with no Russian translation renders the Uzbek
 * text rather than a key name or an empty string, because a person reading a half-built screen should still be
 * able to use it. `messages.test.ts` fails when the two dictionaries drift apart, so "no Russian yet" is a
 * visible gap rather than a silent one.
 *
 * Why the client owns all of this: the server's `message` field carries an English developer description of an
 * error code (`app/contracts/errors.py`), and the client has always mapped the *code* to its own sentence. So
 * there is no language negotiation to do over HTTP - every word a person reads is chosen here.
 *
 * Interpolation is deliberately tiny: `{name}` placeholders, no plural rules engine. Uzbek has no plural
 * agreement after a number and the Russian copy here avoids constructions that need one; a screen that truly
 * needs plural forms should ask for a real library rather than grow one here by accident.
 */
import { messages, type MessageKey } from "./messages";

export type Locale = "uz" | "ru";

export const LOCALES: ReadonlyArray<{ value: Locale; label: string }> = [
  { value: "uz", label: "O'zbekcha" },
  { value: "ru", label: "Русский" },
];

const STORAGE_KEY = "elchi.lang";
export const DEFAULT_LOCALE: Locale = "uz";

function readStored(): Locale {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "ru" || stored === "uz" ? stored : DEFAULT_LOCALE;
  } catch {
    // Private browsing, blocked storage: the default is a working answer, not an error.
    return DEFAULT_LOCALE;
  }
}

let current: Locale = typeof window === "undefined" ? DEFAULT_LOCALE : readStored();
const listeners = new Set<() => void>();

export function getLocale(): Locale {
  return current;
}

export function setLocale(locale: Locale): void {
  if (locale === current) return;
  current = locale;
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // The choice still applies to this session even when it cannot be remembered.
  }
  if (typeof document !== "undefined") document.documentElement.lang = locale;
  listeners.forEach((listener) => listener());
}

/** `useSyncExternalStore` needs both of these; components subscribe through `useLocale` in `react.ts`. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export type { MessageKey };

/**
 * The sentence for a key in the active language.
 *
 * @param key one of the keys in `messages.ts` - a wrong one is a type error, not a runtime surprise
 * @param values `{placeholder}` substitutions
 */
export function translate(key: MessageKey, values?: Record<string, string | number>): string {
  const entry = messages[key];
  const text = (current === "ru" ? entry.ru : entry.uz) || entry.uz;
  if (!values) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match,
  );
}

/**
 * The same lookup for a key that is only known at runtime - a status, an error code, a match type.
 *
 * Returns `undefined` when the code has no entry, so the caller can decide what an unknown value looks like.
 * That decision matters: a status pill falls back to the raw code (which an operator can at least report),
 * while an error falls back to the server's own message (which carries the reason).
 */
export function translateDynamic(key: string, values?: Record<string, string | number>): string | undefined {
  if (!Object.prototype.hasOwnProperty.call(messages, key)) return undefined;
  return translate(key as MessageKey, values);
}
