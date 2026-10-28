import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: Vite on :10001, /api/* proxied to the Python server on :10000.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 10001,
    allowedHosts: ["boldmini.home"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:10000",
        changeOrigin: true,
      },
    },
  },
});
