// Theme bootstrap: the design tokens are static CSS in tokens.css; the only
// runtime job is flipping data-theme on <html> and remembering the choice.

const KEY = "boldtrader-theme";

export type Theme = "light" | "dark";

export function initialTheme(): Theme {
  const saved = localStorage.getItem(KEY);
  return saved === "dark" ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function toggleTheme(current: Theme): Theme {
  const next: Theme = current === "dark" ? "light" : "dark";
  localStorage.setItem(KEY, next);
  applyTheme(next);
  return next;
}
