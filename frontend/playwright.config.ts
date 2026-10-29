// Playwright config for the single M7-exit smoke (ticket #50).
// The smoke drives the Vite dev server on :10001 (which proxies /api to
// the Python backend on :10000). Both servers are auto-started here; an
// already-running stack is reused (reuseExistingServer).

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 90_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:10001",
  },
  webServer: [
    {
      command: ".venv/bin/python -m src.server --port 10000",
      cwd: "..",
      url: "http://127.0.0.1:10000/api/v1/searches?page=1",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      command: "npx vite --port 10001",
      cwd: ".",
      url: "http://127.0.0.1:10001/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});
