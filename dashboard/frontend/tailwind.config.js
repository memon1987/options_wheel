/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        profit: '#10b981',
        loss: '#ef4444',
        warning: '#f59e0b',
      },
    },
  },
  plugins: [],
}
