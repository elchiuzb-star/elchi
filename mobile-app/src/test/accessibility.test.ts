/**
 * Accessibility rules the client has to keep, checked against the source.
 *
 * These are not opinions about markup - each one is a way a screen stops working for somebody:
 *
 * * a button whose only content is an icon announces as "button" and nothing else, so a blind user is told
 *   there is a control but not what it does;
 * * a `placeholder` is not a name: it vanishes the moment someone types, and assistive technology does not
 *   treat it as a label;
 * * a `<div onClick>` is invisible to the keyboard and to a screen reader's control list;
 * * an `<img>` with no `alt` is announced as its file name, or skipped.
 *
 * They are asserted over the source rather than over a rendered tree because the alternative - rendering all
 * forty-odd screens, each of which needs a session and a server - would test almost nothing else.
 *
 * `src/app/App.tsx` is excluded: it is the untouched design prototype kept as the visual reference, and its
 * screens are never rendered (the module re-exports `ConnectedApp`).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** `src/`. `fileURLToPath` rather than `url.pathname`, which yields `/D:/...` on Windows. */
const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const EXCLUDED = new Set(["App.tsx"]);

function sources(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sources(full, found);
    } else if (entry.endsWith(".tsx") && !entry.endsWith(".test.tsx") && !EXCLUDED.has(entry)) {
      found.push(full);
    }
  }
  return found;
}

const FILES = sources(ROOT).map((path) => ({ path: relative(ROOT, path), text: readFileSync(path, "utf8") }));

function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

describe("every control says what it is", () => {
  it("has no icon-only button without an accessible name", () => {
    const offenders: string[] = [];
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<button\b(?<attrs>[^>]*?)>(?<body>[\s\S]*?)<\/button>/g)) {
        const attrs = match.groups?.attrs ?? "";
        if (attrs.includes("aria-label") || attrs.includes("title=")) continue;
        const body = (match.groups?.body ?? "")
          .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
          .replace(/<[A-Z][A-Za-z0-9]*\b[^>]*\/>/g, "")
          .replace(/\s+/g, "");
        if (!body) offenders.push(`${path}:${lineOf(text, match.index ?? 0)}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("never uses a placeholder as a field's only name", () => {
    const offenders: string[] = [];
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<input\b(?<attrs>[^>]*?)\/?>/g)) {
        const attrs = match.groups?.attrs ?? "";
        if (!attrs.includes("placeholder=")) continue;
        if (attrs.includes("aria-label") || attrs.includes('type="checkbox"') || attrs.includes('type="radio"')) continue;
        // A wrapping <label> names the field too; look back far enough to find one.
        const before = text.slice(Math.max(0, (match.index ?? 0) - 900), match.index);
        if (!before.includes("<label")) offenders.push(`${path}:${lineOf(text, match.index ?? 0)}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("has no clickable <div> without a role", () => {
    const offenders: string[] = [];
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<div\b[^>]*\bonClick=/g)) {
        const chunk = text.slice(match.index ?? 0, (match.index ?? 0) + 300);
        if (!chunk.includes("role=")) offenders.push(`${path}:${lineOf(text, match.index ?? 0)}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("has no <img> without alt text", () => {
    const offenders: string[] = [];
    for (const { path, text } of FILES) {
      for (const match of text.matchAll(/<img\b[^>]*>/g)) {
        if (!match[0].includes("alt=")) offenders.push(`${path}:${lineOf(text, match.index ?? 0)}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
