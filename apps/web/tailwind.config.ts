import type { Config } from "tailwindcss";

// Default utilities only — no custom theme, no tokens. This is a test harness.
export default {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
} satisfies Config;
