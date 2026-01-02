/**
 * App Themes - Tokyo Night variants
 *
 * Provides Tokyo Night Light and Dark themes for the entire application,
 * including xterm.js terminals. The theme affects both the app UI (via CSS class)
 * and the terminal color scheme.
 *
 * Default theme is Tokyo Night Light.
 */

import type { ITheme } from "@xterm/xterm";

export type AppThemeName = "tokyo-night-light" | "tokyo-night-dark";

// Alias for backward compatibility
export type TerminalThemeName = AppThemeName;

export const APP_THEME_STORAGE_KEY = "trainsh:app-theme";

export function normalizeAppThemeName(name: AppThemeName | string | null | undefined): AppThemeName {
  return name === "tokyo-night-dark" ? "tokyo-night-dark" : "tokyo-night-light";
}

export function getStoredAppTheme(): AppThemeName | null {
  if (typeof window === "undefined") return null;
  const value = window.localStorage.getItem(APP_THEME_STORAGE_KEY);
  if (value === "tokyo-night-light" || value === "tokyo-night-dark") {
    return value;
  }
  return null;
}

/**
 * Tokyo Night Light theme
 * Based on https://github.com/enkia/tokyo-night-vscode-theme
 */
export const TOKYO_NIGHT_LIGHT: ITheme = {
  background: "#D5D6DB",
  foreground: "#343B58",
  cursor: "#343B58",
  cursorAccent: "#D5D6DB",
  selectionBackground: "#99A7DF80",
  selectionForeground: "#343B58",
  selectionInactiveBackground: "#99A7DF50",
  black: "#0F0F14",
  red: "#8C4351",
  green: "#485E30",
  yellow: "#7A4F10",
  blue: "#34548A",
  magenta: "#5A4A78",
  cyan: "#0F4B6E",
  white: "#343B58",
  brightBlack: "#545C7E",
  brightRed: "#8C4351",
  brightGreen: "#485E30",
  brightYellow: "#7A4F10",
  brightBlue: "#34548A",
  brightMagenta: "#5A4A78",
  brightCyan: "#0F4B6E",
  brightWhite: "#343B58",
};

/**
 * Tokyo Night Dark theme (Storm variant)
 * Based on https://github.com/enkia/tokyo-night-vscode-theme
 */
export const TOKYO_NIGHT_DARK: ITheme = {
  background: "#1A1B26",
  foreground: "#A9B1D6",
  cursor: "#C0CAF5",
  cursorAccent: "#1A1B26",
  selectionBackground: "#33467C80",
  selectionForeground: "#C0CAF5",
  selectionInactiveBackground: "#33467C50",
  black: "#15161E",
  red: "#F7768E",
  green: "#9ECE6A",
  yellow: "#E0AF68",
  blue: "#7AA2F7",
  magenta: "#BB9AF7",
  cyan: "#7DCFFF",
  white: "#A9B1D6",
  brightBlack: "#414868",
  brightRed: "#F7768E",
  brightGreen: "#9ECE6A",
  brightYellow: "#E0AF68",
  brightBlue: "#7AA2F7",
  brightMagenta: "#BB9AF7",
  brightCyan: "#7DCFFF",
  brightWhite: "#C0CAF5",
};

/**
 * All available terminal themes
 */
export const TERMINAL_THEMES: Record<AppThemeName, ITheme> = {
  "tokyo-night-light": TOKYO_NIGHT_LIGHT,
  "tokyo-night-dark": TOKYO_NIGHT_DARK,
};

// Alias for app-wide theme access
export const APP_THEMES = TERMINAL_THEMES;

/**
 * Default app/terminal theme
 */
export const DEFAULT_APP_THEME: AppThemeName = "tokyo-night-light";
export const DEFAULT_TERMINAL_THEME = DEFAULT_APP_THEME;

/**
 * Get terminal theme by name, falls back to default if not found
 */
export function getTerminalTheme(name: AppThemeName | string | null | undefined): ITheme {
  if (name && name in TERMINAL_THEMES) {
    return TERMINAL_THEMES[name as AppThemeName];
  }
  return TERMINAL_THEMES[DEFAULT_APP_THEME];
}

/**
 * Check if theme is dark mode
 */
export function isThemeDark(name: AppThemeName | string | null | undefined): boolean {
  return name === "tokyo-night-dark";
}

/**
 * Apply app theme to document (adds/removes 'dark' class)
 */
export function applyAppTheme(name: AppThemeName | string | null | undefined): void {
  if (typeof document === "undefined") return;

  const normalized = normalizeAppThemeName(name);
  const isDark = isThemeDark(normalized);
  document.documentElement.classList.toggle("dark", isDark);

  try {
    window.localStorage.setItem(APP_THEME_STORAGE_KEY, normalized);
  } catch {
    // Ignore storage errors (e.g., private mode, quota exceeded)
  }
}

/**
 * Theme display info for settings UI
 */
export const APP_THEME_OPTIONS: Array<{
  value: AppThemeName;
  label: string;
  description: string;
}> = [
  {
    value: "tokyo-night-light",
    label: "Tokyo Night Light",
    description: "Light theme with soft blue-gray tones",
  },
  {
    value: "tokyo-night-dark",
    label: "Tokyo Night Dark",
    description: "Dark theme with vibrant neon colors",
  },
];

// Alias for backward compatibility
export const TERMINAL_THEME_OPTIONS = APP_THEME_OPTIONS;
