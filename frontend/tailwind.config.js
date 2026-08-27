/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)", xl: "16px", "2xl": "20px" },
      fontFamily: { sans: ["Geist","Instrument Sans","ui-sans-serif","system-ui"], mono: ["Geist Mono","ui-monospace"] },
      boxShadow: { soft: "0 1px 2px rgba(16,24,40,.06), 0 4px 12px rgba(16,24,40,.06)", elevated: "0 8px 24px rgba(16,24,40,.08)", glow: "0 0 24px hsl(var(--glow) / 0.18)" },
      keyframes: {
        fadeIn: { "0%": { opacity: 0, transform: "translateY(6px)" }, "100%": { opacity: 1, transform: "translateY(0)" } },
        scaleIn: { "0%": { opacity:0, transform:"scale(.98)" }, "100%": { opacity:1, transform:"scale(1)" } },
      },
      animation: { fadeIn: "fadeIn 0.5s cubic-bezier(.22,1,.36,1) both", scaleIn: "scaleIn 0.25s ease both" },
    },
  },
  darkMode: "class",
  plugins: [],
}
