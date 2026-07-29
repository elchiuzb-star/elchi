import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useColorScheme } from "nativewind";
import {
  DarkTheme as NavDarkTheme,
  DefaultTheme as NavLightTheme,
  type Theme as NavTheme,
} from "@react-navigation/native";
import type { ThemeMode } from "@/core/types";
import { colorsFor, type ThemeColors } from "./tokens";

type ThemeContextValue = {
  /** User preference: light | dark | system. */
  themeMode: ThemeMode;
  setThemeMode: (m: ThemeMode) => void;
  /** Resolved scheme after applying the preference. */
  scheme: "light" | "dark";
  colors: ThemeColors;
  navTheme: NavTheme;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Owns the theme preference and pushes it into NativeWind's color scheme, which
 * drives the `dark:` variant, the CSS-variable tokens in global.css, and (via
 * `colorScheme` here) the React Navigation theme and raw token access — so every
 * styling channel resolves to the same light/dark state.
 *
 * Defaults to "dark", matching the web app's initial theme.
 */
export function ThemeProvider({
  children,
  initialMode = "dark",
}: {
  children: ReactNode;
  initialMode?: ThemeMode;
}) {
  const { colorScheme, setColorScheme } = useColorScheme();
  const [themeMode, setThemeMode] = useState<ThemeMode>(initialMode);

  useEffect(() => {
    setColorScheme(themeMode);
  }, [themeMode, setColorScheme]);

  const scheme: "light" | "dark" = colorScheme === "dark" ? "dark" : "light";
  const colors = colorsFor(scheme);

  const value = useMemo<ThemeContextValue>(() => {
    const base = scheme === "dark" ? NavDarkTheme : NavLightTheme;
    const navTheme: NavTheme = {
      ...base,
      colors: {
        ...base.colors,
        primary: colors.primary,
        background: colors.background,
        card: colors.card,
        text: colors.foreground,
        border: colors.border,
        notification: colors.destructive,
      },
    };
    return { themeMode, setThemeMode, scheme, colors, navTheme };
  }, [themeMode, scheme, colors]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within <ThemeProvider>");
  return ctx;
}
