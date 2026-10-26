import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        "surface-2": token("surface-2"),
        line: token("border"),
        ink: token("text"),
        "ink-2": token("text-2"),
        "ink-3": token("text-3"),
        brand: token("brand"),
        "brand-strong": token("brand-strong"),
        "brand-soft": token("brand-soft"),
        "on-brand": token("on-brand"),
        good: token("good"),
        warning: token("warning"),
        serious: token("serious"),
        critical: token("critical"),
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      borderRadius: { card: "12px" },
    },
  },
  plugins: [],
};

export default config;
