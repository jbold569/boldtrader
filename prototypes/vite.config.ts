import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Shared prototype app. Port 10050 per map #14 notes; LAN-visible for phone review.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 10050,
    host: true,
  },
});
