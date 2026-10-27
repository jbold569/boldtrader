import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Shared prototype app. Port 10001: only 10000-10010/tcp are open on the LAN
// (firewall task #31). Phone browses http://boldmini.home:10001 — the host
// name must stay in allowedHosts (Vite rejects unknown Host headers).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 10001,
    host: true,
    allowedHosts: ["boldmini.home"],
  },
});
