/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}'
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        serif: ['Merriweather', 'serif']
      },
      colors: {
        risk: {
          green: '#16a34a',
          amber: '#f59e0b',
          red: '#dc2626'
        }
      }
    }
  },
  plugins: []
}
