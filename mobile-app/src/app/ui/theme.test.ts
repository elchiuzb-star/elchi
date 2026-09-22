/**
 * The theme layer, and the rule that makes it possible.
 *
 * Dark mode did not ship broken in this app - it shipped *dead*. The `.dark` block existed in the stylesheet
 * and nothing could ever add the class, and even if something had, several thousand hard-coded colour
 * literals across the screens would have stayed bright. Both halves are asserted here: the store that adds
 * the class, and a source-level guard that no screen goes back to writing its own hex.
 */
import { beforeEach, describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { resolvedTheme, setThemeMode, startTheme, themeMode } from "./theme";

const SRC = path.resolve(__dirname, "../..");

describe("theme mode", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
    setThemeMode("system");
  });

  it("puts the class on the document, which is what every token hangs off", () => {
    setThemeMode("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    setThemeMode("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("tells the browser which controls to draw, so scrollbars match the page", () => {
    setThemeMode("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
  });

  it("remembers the choice across a launch", () => {
    setThemeMode("dark");
    expect(window.localStorage.getItem("elchi_theme_mode")).toBe("dark");
  });

  it("resolves `system` rather than storing a colour, so the device can change its mind", () => {
    setThemeMode("system");
    expect(themeMode()).toBe("system");
    expect(["light", "dark"]).toContain(resolvedTheme());
  });

  it("applies before the first render, so a dark launch has no white flash", () => {
    setThemeMode("dark");
    document.documentElement.classList.remove("dark");
    startTheme();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

/** Every `.tsx` under src, so a new screen is covered the moment it is written. */
function screens(): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx")) found.push(full);
    }
  };
  walk(SRC);
  return found;
}

describe("colour lives in the theme, not in the screens", () => {
  /**
   * One literal is allowed, on the one line that explains itself: `cssColor()` resolves a token for the map
   * renderer, which draws into WebGL and never sees the stylesheet, and a resolver needs something to fall
   * back to when there is no document at all.
   */
  const ALLOWED = new Map([["components/maps/YandexMap.tsx", new Set(["#2258E6"])]]);

  it("has no hard-coded colour literal left in any component", () => {
    const offenders: string[] = [];
    for (const file of screens()) {
      const relative = path.relative(SRC, file).replace(/\\/g, "/");
      const text = fs.readFileSync(file, "utf8");
      const allowed = ALLOWED.get(relative) ?? new Set<string>();
      const hits = (text.match(/#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b/g) ?? []).filter((hit) => !allowed.has(hit));
      if (hits.length) offenders.push(`${relative}: ${[...new Set(hits)].join(" ")}`);
    }
    expect(offenders, "use a theme token - a literal cannot follow light/dark (styles/theme.css)").toEqual([]);
  });

  it("has no opaque literal white or black utility either", () => {
    const offenders: string[] = [];
    for (const file of screens()) {
      const text = fs.readFileSync(file, "utf8");
      // `bg-black/45` is a scrim - an occlusion rather than a surface, correct at low alpha in either theme,
      // and what the reference client uses. An *opaque* white or black is the thing that breaks in the dark.
      if (/\b(?:bg|text|border)-(?:white|black)\b(?!\/)/.test(text)) {
        offenders.push(path.relative(SRC, file).replace(/\\/g, "/"));
      }
    }
    expect(offenders, "`bg-white` is a surface (`bg-card`); `text-white` is on-brand (`text-primary-foreground`)").toEqual([]);
  });
});
