import { createContext, useContext } from "react";

export type Theme = "light" | "dark";
export const ThemeContext = createContext<Theme>("light");
export const useTheme = () => useContext(ThemeContext);

export const VERDICT_LABEL: Record<string, string> = {
  match: "MATCH",
  not_match: "NO",
  unsure: "SURE?",
  pending: "SIFTING",
};

export function verdictKey(v: string | null): string {
  return v ?? "pending";
}

export function confidenceColor(conf: number): string {
  return conf >= 0.8
    ? "var(--ok)"
    : conf >= 0.6
      ? "var(--warn)"
      : "var(--bad)";
}
