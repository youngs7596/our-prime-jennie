/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Raydium Neon Theme Colors
        raydium: {
          dark: "#0C0D14",
          darker: "#080910",
          card: "#131928",
          cardHover: "#1a2235",
          purple: "#7C3AED",
          purpleLight: "#A855F7",
          purpleBright: "#C084FC",
          blue: "#3B82F6",
          cyan: "#22D3EE",
          cyanLight: "#67E8F9",
          pink: "#EC4899",
          magenta: "#D946EF",
        },
        // Jennie (하위 호환 - Raydium 매핑)
        jennie: {
          pink: "#EC4899",
          purple: "#7C3AED",
          blue: "#22D3EE",
          gold: "#FBBF24",
          dark: "#0C0D14",
          darker: "#080910",
        },
        profit: {
          positive: "#10B981",
          negative: "#EF4444",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Inter", "Pretendard", "system-ui", "sans-serif"],
        display: ["Outfit", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      keyframes: {
        "accordion-down": {
          from: { height: 0 },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: 0 },
        },
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 20px rgba(124, 58, 237, 0.4)" },
          "50%": { boxShadow: "0 0 40px rgba(124, 58, 237, 0.7)" },
        },
        "neon-pulse": {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.7 },
        },
        "gradient-shift": {
          "0%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
          "100%": { backgroundPosition: "0% 50%" },
        },
        "float": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-10px)" },
        },
        "shimmer": {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "glow-border": {
          "0%, 100%": { borderColor: "rgba(124, 58, 237, 0.5)" },
          "50%": { borderColor: "rgba(34, 211, 238, 0.5)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
        "neon-pulse": "neon-pulse 2s ease-in-out infinite",
        "gradient-shift": "gradient-shift 3s ease infinite",
        "float": "float 3s ease-in-out infinite",
        "shimmer": "shimmer 2s linear infinite",
        "glow-border": "glow-border 3s ease-in-out infinite",
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "gradient-conic": "conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))",
        "raydium-gradient": "linear-gradient(135deg, #7C3AED 0%, #3B82F6 50%, #22D3EE 100%)",
        "raydium-dark": "linear-gradient(180deg, #0C0D14 0%, #080910 100%)",
        "neon-glow": "radial-gradient(ellipse at center, rgba(124, 58, 237, 0.15) 0%, transparent 70%)",
        // Legacy
        "jennie-gradient": "linear-gradient(135deg, #7C3AED 0%, #3B82F6 50%, #22D3EE 100%)",
      },
      boxShadow: {
        "neon-purple": "0 0 20px rgba(124, 58, 237, 0.5), 0 0 40px rgba(124, 58, 237, 0.3)",
        "neon-cyan": "0 0 20px rgba(34, 211, 238, 0.5), 0 0 40px rgba(34, 211, 238, 0.3)",
        "neon-pink": "0 0 20px rgba(236, 72, 153, 0.5), 0 0 40px rgba(236, 72, 153, 0.3)",
        "card-glow": "0 4px 30px rgba(0, 0, 0, 0.3), 0 0 1px rgba(124, 58, 237, 0.3)",
      },
    },
  },
  plugins: [],
}
