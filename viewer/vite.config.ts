/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// The API server is `cheme serve` (default http://127.0.0.1:8765). Override with
// CHEME_API=http://host:port npm run dev.
const api = process.env.CHEME_API ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: "127.0.0.1",
    proxy: { "/api": { target: api, changeOrigin: false } },
  },
  // three.js (about 570 kB) is its own chunk, loaded only on the /layout route.
  build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 700 },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});
