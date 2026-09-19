import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/v1": { target: "http://127.0.0.1:8000", ws: true },
      "/healthz": { target: "http://127.0.0.1:8000" },
    },
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
});
