// Copyright (c) 2026, Sanjay Kumar and contributors
// For license information, please see license.txt

/**
 * Phase 33 — Accessibility suite.
 *
 * Runs axe-core against the three primary chatbot surfaces and the
 * 375px-wide mobile viewport.  Acceptance per roadmap §33.413:
 *
 *   * Chat view usable end-to-end on a 375px-wide viewport.
 *   * axe-core: zero serious/critical violations on the three main pages.
 *
 * Tests are skipped when ``IDP_TEST_BASE_URL`` is not reachable so the
 * suite doesn't fail in a developer's clean checkout — boot the dev
 * server (``yarn dev`` in ``frontend/``) and re-run.
 */
import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// Filter axe results down to the WCAG 2.1 AA bar — colour-contrast,
// ARIA usage, keyboard traps, etc.  We don't gate on best-practice
// rules so the suite doesn't churn on stylistic preferences.
const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

async function expectNoSeriousViolations(page) {
  const results = await new AxeBuilder({ page })
    .withTags(A11Y_TAGS)
    .analyze()

  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  )

  if (serious.length) {
    // Log the readable summary into the test output so a CI failure
    // points straight at the offending nodes.
    // eslint-disable-next-line no-console
    console.error(
      'Serious/critical a11y violations:',
      JSON.stringify(
        serious.map((v) => ({
          id: v.id,
          impact: v.impact,
          nodes: v.nodes.map((n) => n.html).slice(0, 3),
          help: v.help,
        })),
        null,
        2,
      ),
    )
  }

  expect(serious, 'Expected zero serious/critical axe-core violations').toEqual(
    [],
  )
}

test.describe('IDP chat — a11y baseline', () => {
  test('chat home view passes axe checks', async ({ page }) => {
    await page.goto('/')
    // Wait for the shell to mount — the skip link is a stable anchor.
    await page.waitForSelector('.idp-skip-link')
    await expectNoSeriousViolations(page)
  })

  test('skip link is keyboard-accessible and reveals on focus', async ({
    page,
  }) => {
    await page.goto('/')
    await page.keyboard.press('Tab')
    const skip = page.locator('.idp-skip-link')
    await expect(skip).toBeFocused()
    // Reveal-on-focus is implemented as a CSS transition; assert the
    // computed top is non-negative once focused.
    const top = await skip.evaluate((el) =>
      parseFloat(getComputedStyle(el).top),
    )
    expect(top).toBeGreaterThanOrEqual(0)
  })

  test('conversation list / sidebar passes axe checks', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('#idp-sidebar')
    await expectNoSeriousViolations(page)
  })

  // The confirmation card surface is only reachable once an extraction
  // proposes one — covered by a route-stubbed scenario in CI.  In dev
  // we just assert the card-shell render path when present.
  test('confirmation card (if rendered) passes axe checks', async ({
    page,
  }) => {
    await page.goto('/')
    const card = page.locator('.idp-confirmation-card').first()
    if (await card.count()) {
      await expectNoSeriousViolations(page)
    } else {
      test.skip(true, 'No confirmation card rendered in this dev state.')
    }
  })
})

test.describe('IDP chat — mobile 375px', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('hamburger is visible and toggles the drawer', async ({ page }) => {
    await page.goto('/')
    const hamburger = page.locator('.idp-hamburger')
    await expect(hamburger).toBeVisible()
    await hamburger.click()
    const sidebar = page.locator('#idp-sidebar')
    await expect(sidebar).toHaveClass(/idp-sidebar--open/)
  })

  test('chat view at 375px passes axe checks', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('.idp-skip-link')
    await expectNoSeriousViolations(page)
  })
})
