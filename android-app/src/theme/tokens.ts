// Programmatic access to the Elchi design tokens (ported from
// frontend/src/styles/theme.css). Use these when a raw color value is needed
// outside of NativeWind classNames — e.g. React Navigation themes, status bar,
// SVG charts, map styles.

export const lightColors = {
  // no `as const`: values stay `string` so darkColors can hold different hexes.
  background: "#F4F6FB",
  foreground: "#111726",
  card: "#FFFFFF",
  cardForeground: "#111726",
  popover: "#FFFFFF",
  popoverForeground: "#111726",
  primary: "#2258E6",
  primaryForeground: "#FFFFFF",
  secondary: "#E9EEF9",
  secondaryForeground: "#2A3346",
  muted: "#EEF1F8",
  mutedForeground: "#5B6577",
  accent: "#E4EBFD",
  accentForeground: "#2258E6",
  feruza: "#3B82F6",
  destructive: "#D93B44",
  destructiveForeground: "#FFFFFF",
  success: "#1E9E5B",
  warning: "#C98A16",
  info: "#2C7BD0",
  border: "rgba(17, 23, 38, 0.09)",
  input: "#EEF1F8",
  ring: "#2258E6",
};

export type ThemeColors = typeof lightColors;

export const darkColors: ThemeColors = {
  background: "#0B1020",
  foreground: "#E9EDF6",
  card: "#141B2E",
  cardForeground: "#E9EDF6",
  popover: "#182034",
  popoverForeground: "#E9EDF6",
  primary: "#4A78F0",
  primaryForeground: "#FFFFFF",
  secondary: "#1E2740",
  secondaryForeground: "#C4CDE0",
  muted: "#182034",
  mutedForeground: "#8A93A8",
  accent: "#16233F",
  accentForeground: "#6AA6FF",
  feruza: "#6AA6FF",
  destructive: "#EF5A63",
  destructiveForeground: "#FFFFFF",
  success: "#35BB78",
  warning: "#E0A93A",
  info: "#5AA6E0",
  border: "rgba(233, 237, 246, 0.10)",
  input: "#1E2740",
  ring: "#4A78F0",
};

export const radius = { sm: 8, md: 10, lg: 14 } as const;

export function colorsFor(scheme: "light" | "dark" | null | undefined): ThemeColors {
  return scheme === "dark" ? darkColors : lightColors;
}
