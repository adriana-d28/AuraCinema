// Vite configuration for the AuraCinema frontend.
//
// Vite is the development server and build tool. The same file also holds the
// configuration for Vitest (the test runner), so there is only one place to look.
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],

  server: {
    // 5173 is the origin already allowed by the backend CORS setting
    // (CORS_ORIGINS=http://localhost:5173 in backend/.env.example).
    // strictPort stops Vite from silently moving to another port that the
    // backend would then reject.
    port: 5173,
    strictPort: true,
  },

  test: {
    // jsdom gives the tests a fake browser (document, window, images...).
    environment: 'jsdom',
    // Runs once before the tests: adds the extra "toBeInTheDocument"-style checks.
    setupFiles: ['./src/test/setup.ts'],
    // CSS is not needed to check behaviour, so it is ignored in tests.
    css: false,
  },
})
