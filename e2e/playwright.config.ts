import { defineConfig, devices } from "@playwright/test";

// 화면(3000) + API(8000) 를 실제로 띄워 브라우저로 처음부터 끝까지 확인한다.
// DB 는 ROOMAX_DATABASE_URL (CI: postgres 서비스). 화면은 미리 빌드해 둘 것 (npm run build, ROOMAX_API_ORIGIN 같게).
const PY = process.env.E2E_PYTHON ?? "python";
// 서비스 워커가 하는 요청도 route 로 가로채게 (PWA 연결 끊김 시험). Playwright 1.49 Chromium 의 실험 옵션
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = "1";
const API = "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  retries: 0,
  workers: 1,  // 같은 DB 를 쓰므로 순서대로
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.E2E_CHROMIUM ? { executablePath: process.env.E2E_CHROMIUM } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } }],
  webServer: [
    {
      command: `${PY} -m alembic upgrade head && ${PY} -m uvicorn app.main:app --port 8000`,
      cwd: "../backend",
      url: `${API}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ROOMAX_ENV: "development",
        ROOMAX_SIGNUP_MODE: "open",
        ROOMAX_STORAGE: "local",
        ROOMAX_UPLOAD_DIR: "/tmp/roomax-e2e/uploads",
        ROOMAX_BACKUP_DIR: "/tmp/roomax-e2e/backups",
        ROOMAX_MAIL_MODE: "file",
        ROOMAX_MAIL_OUTBOX_DIR: "/tmp/roomax-e2e/mail",
        ROOMAX_FIELD_KEY: process.env.ROOMAX_FIELD_KEY ?? "4Rx4_n81zQhKciPa32MdTzLKFAU9U-Tmu0tu0Hn2uJI=",  // 시험 전용
        ROOMAX_DATABASE_URL: process.env.ROOMAX_DATABASE_URL ?? "postgresql://roomax:roomax@127.0.0.1:5432/roomax_e2e",
        ANTHROPIC_API_KEY: "",  // AI 비서는 '연결 안 됨' 상태를 확인
      },
    },
    {
      command: "npm run start -- -p 3000",
      cwd: "../frontend",
      url: "http://localhost:3000/login",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { ROOMAX_API_ORIGIN: API },
    },
  ],
});
