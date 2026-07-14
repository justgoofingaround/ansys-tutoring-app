import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

// Dev: Vite on :5173 proxies /api to FastAPI on :8000 (same-origin cookies).
// Prod: `npm run build` -> dist/, served by FastAPI itself (one origin).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
});
