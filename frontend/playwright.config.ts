// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Phase 33 — Playwright config for the IDP frontend a11y suite.
 *
 * The suite runs against the dev server (``yarn dev``) on the default
 * Vite port; the ``IDP_TEST_BASE_URL`` env var lets CI point at a
 * built bundle behind ``bench serve`` instead.
 */
import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.IDP_TEST_BASE_URL || 'http://localhost:5173'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
    // Default to a desktop viewport; the responsive test below
    // overrides this with the 375px mobile case.
    viewport: { width: 1280, height: 720 },
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-safari',
      // iPhone 13 mini — the 375px-wide acceptance viewport from the
      // Phase 33 roadmap (§33).
      use: { ...devices['iPhone 13 Mini'] },
    },
  ],
})
