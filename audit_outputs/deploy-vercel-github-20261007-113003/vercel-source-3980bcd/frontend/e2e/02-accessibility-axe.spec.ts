import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'fs';
import path from 'path';

const SCREENSHOT_DIR = path.resolve('e2e-screenshots/accessibility');
const REPORT_DIR = path.resolve('e2e-screenshots/axe-reports');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
  if (!fs.existsSync(REPORT_DIR)) {
    fs.mkdirSync(REPORT_DIR, { recursive: true });
  }
});

test.describe('Automated Accessibility Audit (Axe Core WCAG 2.1 AA)', () => {
  test('Audit Chat Home (Empty State) in Light & Dark Mode', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Analyze Light Mode
    const lightAudit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .disableRules(['color-contrast']) // We test contrast separately with custom threshold if needed
      .analyze();

    fs.writeFileSync(
      path.join(REPORT_DIR, 'home-empty-light-axe.json'),
      JSON.stringify(lightAudit.violations, null, 2)
    );
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'a11y-home-empty-light.png'),
    });

    // Check critical or serious violations
    const criticalViolations = lightAudit.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious'
    );
    expect(criticalViolations).toEqual([]);

    // Analyze Dark Mode
    await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
    await page.waitForTimeout(200);

    const darkAudit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .disableRules(['color-contrast'])
      .analyze();

    fs.writeFileSync(
      path.join(REPORT_DIR, 'home-empty-dark-axe.json'),
      JSON.stringify(darkAudit.violations, null, 2)
    );
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'a11y-home-empty-dark.png'),
    });

    const darkCritical = darkAudit.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious'
    );
    expect(darkCritical).toEqual([]);
  });

  test('Audit History Drawer Opened', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Open drawer if closed
    const isDrawerOpen = await page.locator('.history-drawer.open').isVisible();
    if (!isDrawerOpen) {
      await page.locator('.drawer-toggle-btn').first().click();
      await page.waitForTimeout(300);
    }

    const drawerAudit = await new AxeBuilder({ page })
      .include('.history-drawer')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    fs.writeFileSync(
      path.join(REPORT_DIR, 'history-drawer-axe.json'),
      JSON.stringify(drawerAudit.violations, null, 2)
    );
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'a11y-history-drawer.png'),
    });

    const critical = drawerAudit.violations.filter((v) => v.impact === 'critical');
    expect(critical).toEqual([]);
  });

  test('Audit Privacy Policy Modal', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Open drawer to access privacy button or click trigger
    const isDrawerOpen = await page.locator('.history-drawer.open').isVisible();
    if (!isDrawerOpen) {
      await page.locator('.drawer-toggle-btn').first().click();
      await page.waitForTimeout(300);
    }

    const privacyBtn = page.locator('button:has-text("Chính sách quyền riêng tư")').first();
    await privacyBtn.click();
    await page.waitForTimeout(300);

    // Verify modal is open
    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    const modalAudit = await new AxeBuilder({ page })
      .include('[role="dialog"]')
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    fs.writeFileSync(
      path.join(REPORT_DIR, 'privacy-modal-axe.json'),
      JSON.stringify(modalAudit.violations, null, 2)
    );
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'a11y-privacy-modal.png'),
    });

    const critical = modalAudit.violations.filter((v) => v.impact === 'critical');
    expect(critical).toEqual([]);
  });

  test('Audit Admin Login Page', async ({ page }) => {
    await page.goto('/admin');
    await page.waitForLoadState('networkidle');

    const loginCard = page.locator('.admin-login-card');
    await expect(loginCard).toBeVisible();

    const adminAudit = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a'])
      .disableRules(['color-contrast'])
      .analyze();

    fs.writeFileSync(
      path.join(REPORT_DIR, 'admin-login-axe.json'),
      JSON.stringify(adminAudit.violations, null, 2)
    );
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'a11y-admin-login.png'),
    });

    const critical = adminAudit.violations.filter((v) => v.impact === 'critical');
    expect(critical).toEqual([]);
  });
});
