import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "media",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Groww-ish accent
        brand: {
          DEFAULT: "#00b386",
          600: "#00996f",
          700: "#007a59",
        },
        up: "#16a34a",
        down: "#dc2626",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        flashup: { "0%": { backgroundColor: "rgba(22,163,74,0.18)" }, "100%": { backgroundColor: "transparent" } },
        flashdown: { "0%": { backgroundColor: "rgba(220,38,38,0.18)" }, "100%": { backgroundColor: "transparent" } },
      },
      animation: {
        flashup: "flashup 0.7s ease-out",
        flashdown: "flashdown 0.7s ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
