/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0c', // Midnight Black
        panel: '#141418', // Dark Grey Panel
        border: '#2a2a32', // Metallic Border
        accent: '#06b6d4', // Cyan / Neon Blue
        text: '#ededed', // Pure White Text
        muted: '#a1a1aa', // Grey Text
      },
      fontFamily: {
        sans: ['"Barlow Semi Condensed"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};