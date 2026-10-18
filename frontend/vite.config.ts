import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Dev server proxies the API so the app always talks to a same-origin /api (as behind nginx).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_URL ?? "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: {
    sourcemap: false,
    // never inline assets as data: URIs; the nginx CSP only allows same-origin fonts and images
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 900,
  },
});
