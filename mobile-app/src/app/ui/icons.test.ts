/**
 * The icon set is one set.
 *
 * Two libraries drawing the same product is the failure this guards against: it is not a build error, it does
 * not show up in a screenshot of one screen, and it is only visible when two screens sit side by side - by
 * which point half the app is on the wrong set. So the rule is asserted mechanically: every icon comes
 * through `ui/icons`, and nothing imports an icon library directly.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import * as icons from "./icons";

const SRC = path.resolve(__dirname, "../..");

function sources(): string[] {
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name)) found.push(full);
    }
  };
  walk(SRC);
  return found;
}

describe("icons", () => {
  it("is the only door to an icon library", () => {
    const offenders: string[] = [];
    for (const file of sources()) {
      const relative = path.relative(SRC, file).replace(/\\/g, "/");
      if (relative === "app/ui/icons.ts") continue;
      const text = fs.readFileSync(file, "utf8");
      if (/from\s+["'](?:lucide-react|@phosphor-icons\/react)["']/.test(text)) offenders.push(relative);
    }
    expect(offenders, "import icons from `ui/icons`, so the set can be changed in one place").toEqual([]);
  });

  it("still answers to every name the screens call it by", () => {
    // A sample across the map rather than all 105: these are the ones whose Phosphor name is nothing like the
    // name the screens use, so a broken alias would be silent.
    for (const name of ["Home", "ChevronRight", "Send", "Search", "Menu", "Route", "Loader2", "Save", "Upload"]) {
      expect(icons, `${name} is missing from the icon set`).toHaveProperty(name);
    }
  });

  it("has no name pointing at nothing", () => {
    const missing = Object.entries(icons)
      .filter(([, value]) => value === undefined)
      .map(([name]) => name);
    expect(missing).toEqual([]);
  });
});
