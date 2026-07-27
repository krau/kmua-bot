import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// The bundle is served by the bot's FastAPI app from kmua/webapp/dist, so the build
// writes straight there. `pnpm dev` instead runs on its own origin and proxies /api
// to the bot, which needs webapp_allow_origins set on the backend.
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: fileURLToPath(new URL("../kmua/webapp/dist", import.meta.url)),
    emptyOutDir: true,
    // Hashed filenames under assets/ let the server cache them immutably; see
    // kmua/webapp/static.py.
    assetsDir: "assets",
    sourcemap: false,
    target: "es2022",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8180",
        // Keep the Origin header: the backend's dev CORS allowlist matches on it.
        changeOrigin: false,
      },
    },
  },
});
