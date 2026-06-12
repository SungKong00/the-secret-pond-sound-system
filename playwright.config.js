const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/web",
  timeout: 30000,
  expect: {
    timeout: 7000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        channel: process.env.PLAYWRIGHT_CHROME_CHANNEL || "chrome",
        viewport: { width: 1440, height: 1000 },
      },
    },
  ],
});
