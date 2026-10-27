import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Shared prototype app. Port 10001: only 10000-10010/tcp are open on the LAN
// (firewall task #31); phone browses http://192.168.86.30:10001.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 10001,
    host: true,
  },
});
