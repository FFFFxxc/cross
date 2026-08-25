import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1 --port 3100",
    url: "http://127.0.0.1:3100/login",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      DATABASE_URL: "postgresql://e2e:e2e@127.0.0.1/e2e",
      ADMIN_PASSWORD_HASH: "$2b$04$9efEjALnPXBhjl5V/2TGse0AxPGLnJb.43.9.4yJyKS5D1mhWiPBa",
      AUTH_SECRET: "e2e-auth-secret-that-is-longer-than-32-characters",
    },
  },
});
