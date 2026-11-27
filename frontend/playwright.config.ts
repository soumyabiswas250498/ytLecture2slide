import { defineConfig } from "@playwright/test";
const externalBaseUrl = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: externalBaseUrl ?? "http://127.0.0.1:5173" },
  webServer: externalBaseUrl
    ? undefined
    : [
        {
          command:
            "sh -c '../backend/.venv/bin/alembic upgrade head && exec ../backend/.venv/bin/python -m app'",
          cwd: "../backend",
          url: "http://127.0.0.1:8000/api/v1/ready",
          env: {
            APP_ENV: "test",
            STORAGE_DIR: "storage/e2e",
            DATABASE_PATH: "storage/e2e/database/app.db",
            TEMP_DIR: "storage/e2e/jobs",
          },
          reuseExistingServer: false,
        },
        {
          command: "npm run dev",
          url: "http://127.0.0.1:5173",
          reuseExistingServer: false,
        },
      ],
});
