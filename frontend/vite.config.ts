import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

export default defineConfig({
  base: "/app-ui/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "../static/app-ui",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
})
