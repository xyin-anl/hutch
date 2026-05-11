"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "hutch-theme";

type Theme = "light" | "dark";

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  const html = document.documentElement;
  if (theme === "dark") html.classList.add("dark");
  else html.classList.remove("dark");
}

function readStoredTheme(): Theme | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    // happy-dom in tests, sandboxed iframes, or storage-disabled browsers all
    // throw here. Treat as "no preference recorded".
  }
  return null;
}

function writeStoredTheme(theme: Theme): void {
  try {
    if (typeof window === "undefined" || !window.localStorage) return;
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // ignore
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const initial = readStoredTheme() ?? "light";
    applyTheme(initial);
    setTheme(initial);
    setMounted(true);
  }, []);

  const flip = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
    writeStoredTheme(next);
  };

  if (!mounted) {
    return <div className="h-7 w-7" aria-hidden />;
  }
  return (
    <button
      type="button"
      onClick={flip}
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      className="grid h-7 w-7 place-items-center rounded border border-neutral-200 text-neutral-600 transition-colors hover:border-neutral-300 hover:text-neutral-900 dark:border-neutral-800 dark:text-neutral-400 dark:hover:border-neutral-700 dark:hover:text-neutral-100"
    >
      <span aria-hidden className="text-sm">
        {theme === "dark" ? "☀" : "☾"}
      </span>
    </button>
  );
}
