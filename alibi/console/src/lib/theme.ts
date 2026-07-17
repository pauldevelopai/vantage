/**
 * Whole-system theme: one class on <html> ('theme-dark' | 'theme-light') that
 * index.css maps onto every page — dark is the Overview's design language,
 * light is the same layout on paper-white. Persisted per browser.
 */

const KEY = 'vantage_theme';
export type Theme = 'dark' | 'light';

export function getTheme(): Theme {
  return (localStorage.getItem(KEY) as Theme) || 'dark';
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.remove('theme-dark', 'theme-light');
  root.classList.add(theme === 'light' ? 'theme-light' : 'theme-dark');
  root.style.colorScheme = theme;
}

export function setTheme(theme: Theme): void {
  localStorage.setItem(KEY, theme);
  applyTheme(theme);
}

export function initTheme(): void {
  applyTheme(getTheme());
}
