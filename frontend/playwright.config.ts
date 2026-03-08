import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: devices["Desktop Chrome"],
    },
  ],
  webServer: [
    {
      command: "uv run python -m uvicorn readmatrix.main:app --host localhost --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/api/health",
      timeout: 120_000,
      reuseExistingServer: true,
    },
    {
      command: "pnpm exec nuxi dev --host localhost --port 3000",
      cwd: ".",
      url: "http://localhost:3000",
      timeout: 120_000,
      reuseExistingServer: true,
      env: {
        NUXT_PUBLIC_API_URL: "http://localhost:8000",
      },
    },
  ],
});
