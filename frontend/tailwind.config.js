/** Design tokens live in src/styles.css as CSS variables (dark default, light theme). */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        raised: token("raised"),
        line: token("line"),
        ink: token("ink"),
        muted: token("muted"),
        faint: token("faint"),
        accent: token("accent"),
        long: token("long"),
        short: token("short"),
        warn: token("warn"),
      },
      fontFamily: {
        sans: ['"Inter Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono Variable"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: { "2xs": ["0.6875rem", { lineHeight: "1rem" }] },
      boxShadow: {
        card: "0 1px 0 rgb(var(--line) / 0.6), 0 8px 24px -12px rgb(0 0 0 / 0.35)",
        glow: "0 0 0 1px rgb(var(--accent) / 0.35), 0 0 24px -4px rgb(var(--accent) / 0.35)",
      },
      keyframes: {
        pulseDot: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        slideIn: { from: { transform: "translateY(8px)", opacity: "0" }, to: { transform: "none", opacity: "1" } },
        flash: { "0%": { backgroundColor: "rgb(var(--accent) / 0.18)" }, "100%": { backgroundColor: "transparent" } },
      },
      animation: {
        pulseDot: "pulseDot 1.6s ease-in-out infinite",
        slideIn: "slideIn 220ms ease-out",
        flash: "flash 1.6s ease-out",
      },
    },
  },
  plugins: [],
};
