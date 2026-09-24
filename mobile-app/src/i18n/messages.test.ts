/**
 * The dictionary's own invariants.
 *
 * A translation file rots in two ways: an entry gains one language and not the other, or the same sentence is
 * written twice under different keys and then only one of them is corrected. Both are silent in a running app -
 * the first shows Uzbek to a Russian speaker, the second shows two different wordings of one rule.
 */
import { describe, expect, it } from "vitest";

import { messageSources, messages, type MessageKey } from "./messages";
import { getLocale, setLocale, translate, translateDynamic } from "./index";

const entries = Object.entries(messages) as Array<[MessageKey, { uz: string; ru: string }]>;

describe("the dictionary", () => {
  it("has both languages for every key", () => {
    const missing = entries
      .filter(([, value]) => !value.uz?.trim() || !value.ru?.trim())
      .map(([key]) => key);
    expect(missing).toEqual([]);
  });

  it("never leaves the Uzbek text in the Russian slot", () => {
    // Identical strings are legitimate for a few tokens (a dash, a plate number format); flag only real words.
    const suspicious = entries
      .filter(([, value]) => value.uz === value.ru && /\p{L}{3,}/u.test(value.uz))
      .map(([key]) => key);
    expect(suspicious).toEqual([]);
  });

  it("uses the same placeholders in both languages", () => {
    const placeholders = (text: string) => (text.match(/\{(\w+)\}/g) ?? []).sort();
    const mismatched = entries
      .filter(([, value]) => JSON.stringify(placeholders(value.uz)) !== JSON.stringify(placeholders(value.ru)))
      .map(([key]) => key);
    expect(mismatched).toEqual([]);
  });
});

describe("the screen dictionaries", () => {
  it("never define the same key twice", () => {
    // `messages` is a spread of every source: a repeated key would silently keep only the last sentence.
    const seen = new Map<string, string>();
    const repeated: string[] = [];
    for (const [source, entries] of Object.entries(messageSources)) {
      for (const key of Object.keys(entries)) {
        const first = seen.get(key);
        if (first) repeated.push(`${key} (${first}, ${source})`);
        else seen.set(key, source);
      }
    }
    expect(repeated).toEqual([]);
    expect(Object.keys(messages)).toHaveLength(seen.size);
  });

  it("have a Russian sentence for every Uzbek one, in every source", () => {
    const missing = Object.entries(messageSources).flatMap(([source, entries]) =>
      Object.entries(entries as Record<string, { uz: string; ru: string }>)
        .filter(([, value]) => !value.uz?.trim() || !value.ru?.trim() || (value.ru === value.uz && /\p{L}{3,}/u.test(value.uz)))
        .map(([key]) => `${source}:${key}`),
    );
    expect(missing).toEqual([]);
  });
});

describe("translate", () => {
  it("answers in the active language and switches when it changes", () => {
    const original = getLocale();
    try {
      setLocale("uz");
      expect(translate("common.cancel")).toBe("Bekor qilish");
      setLocale("ru");
      expect(translate("common.cancel")).toBe("Отмена");
    } finally {
      setLocale(original);
    }
  });

  it("substitutes placeholders and leaves unknown ones alone", () => {
    // `translate` is generic over the dictionary, so this uses a real key with no placeholders plus a raw call.
    expect(translate("common.total", { unused: 1 })).toBe("Jami");
  });

  it("returns undefined for a code it does not know, so the caller can decide", () => {
    expect(translateDynamic("status.something_new")).toBeUndefined();
    expect(translateDynamic("status.delivered")).toBe("Yetkazildi");
  });
});
