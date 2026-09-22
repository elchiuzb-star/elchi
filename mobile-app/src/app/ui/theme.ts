/**
 * Light, dark, or whatever the phone is set to.
 *
 * Ported from the frozen reference client, which offers all three in its settings panel. This client had the
 * `.dark` block in its stylesheet and nothing that could ever add the class, so the dark palette shipped dead.
 *
 * Three choices rather than a switch, because they are three different statements: "always light", "always
 * dark", and "follow the device" - the last being the one most people actually want, and the only one that
 * changes by itself at dusk. `system` keeps listening, so the app follows the phone while it is open.
 *
 * The store is module-level and read through `useSyncExternalStore`, the same shape as the i18n layer, so a
 * change lands on every subscriber at once without a provider wrapped around the tree.
 */
import { useSyncExternalStore } from "react";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "elchi_theme_mode";
const MODES: readonly ThemeMode[] = ["light", "dark", "system"];

let mode: ThemeMode = readStored();
const listeners = new Set<() => void>();

function readStored(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && (MODES as readonly string[]).includes(stored)) return stored as ThemeMode;
  } catch {
    // A private window can refuse storage. The default is then "system", which is the right answer anyway.
  }
  return "system";
}

function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

/** What the person actually sees right now, with `system` already resolved. */
export function resolvedTheme(): "light" | "dark" {
  if (mode === "system") return prefersDark() ? "dark" : "light";
  return mode;
}

function apply(): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("dark", resolvedTheme() === "dark");
  // Tells the browser which scrollbars and form controls to draw, so they match the page instead of staying
  // bright over a dark app.
  root.style.colorScheme = resolvedTheme();
}

export function themeMode(): ThemeMode {
  return mode;
}

export function setThemeMode(next: ThemeMode): void {
  mode = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Not being able to remember the choice is not a reason to refuse it for this session.
  }
  apply();
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Re-render this component whenever the mode changes, or the device changes its mind while on `system`. */
export function useThemeMode(): { mode: ThemeMode; resolved: "light" | "dark"; setMode: (next: ThemeMode) => void } {
  const current = useSyncExternalStore(subscribe, themeMode, () => "system" as ThemeMode);
  return { mode: current, resolved: resolvedTheme(), setMode: setThemeMode };
}

/**
 * Start the theme before React renders, so the first paint is already the right one - otherwise a person who
 * chose dark gets a white flash on every launch.
 */
export function startTheme(): void {
  apply();
  try {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (mode !== "system") return;
      apply();
      listeners.forEach((listener) => listener());
    };
    query.addEventListener("change", onChange);
  } catch {
    // Without matchMedia the stored mode still works; only "follow the device" stops updating live.
  }
}
