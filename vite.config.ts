import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // GitHub project sites are served below /rideweave/. Vercel and local
  // development continue to use the site root.
  base: process.env.GITHUB_ACTIONS === 'true' ? '/rideweave/' : '/',
  plugins: [react()],
  worker: {
    format: 'es',
  },
})
