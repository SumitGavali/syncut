/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0c', // Midnight Black
        panel: '#141418', // Dark Grey Panel
        border: '#2a2a32', // Metallic Border
        accent: '#06b6d4', 'accent-hover': '#22d3ee',
        text: '#ededed',
        muted: '#a1a1aa',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};