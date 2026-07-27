import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// Vitest config is kept separate from vite.config.ts so the build config stays
// free of test-only settings, and so `tsconfig.node.json` can type-check both.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.spec.ts"],
    globals: false,
  },
});
