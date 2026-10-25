import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Flask serves the built studio at /studio. In development, API calls and
// uploaded images are proxied to Flask so the login session cookie is shared.
const FLASK_DEV_SERVER = 'http://localhost:5000'

// https://vite.dev/config/
export default defineConfig({
  base: '/studio/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': FLASK_DEV_SERVER,
      '/static': FLASK_DEV_SERVER,
    },
  },
})
