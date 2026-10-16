import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Pretendard Variable", "Pretendard", "-apple-system", "BlinkMacSystemFont", "system-ui",
          "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "sans-serif"],
      },
      colors: {
        // 사이드바 남색 (디자인 시안)
        navy: { 700: "#1f3a63", 800: "#172d4f", 900: "#11223d", 950: "#0c1930" },
        canvas: "#f3f6fb",
      },
      boxShadow: {
        card: "0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06)",
      },
    },
  },
  plugins: [],
} satisfies Config;
