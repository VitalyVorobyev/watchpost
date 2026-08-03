import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the client runs on Vite's server and talks to the host on 8787.
// In production the host serves web/dist itself, so these paths are same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5183,
    proxy: {
      "/api": { target: "http://127.0.0.1:8787", changeOrigin: true, ws: false },
      "/healthz": { target: "http://127.0.0.1:8787", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
