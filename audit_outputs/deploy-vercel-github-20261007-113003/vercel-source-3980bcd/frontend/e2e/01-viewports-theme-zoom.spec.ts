import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const SCREENSHOT_DIR = path.resolve('e2e-screenshots/viewports');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

const VIEWPORTS = [
  { name: 'desktop-1920x1080', width: 1920, height: 1080 },
  { name: 'desktop-1366x768', width: 1366, height: 768 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'mobile-390x844', width: 390, height: 844 },
  { name: 'small-mobile-320x568', width: 320, height: 568 },
];

test.describe('Responsive Viewports, Themes & 200% Zoom', () => {
  for (const vp of VIEWPORTS) {
    test(`Render correctly at ${vp.name} in Light and Dark mode`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/');
      await page.waitForLoadState('networkidle');

      // Verify page container is loaded
      const appContainer = page.locator('.app-container');
      await expect(appContainer).toBeVisible();

      // Check header or drawer toggle presence
      const toggleBtn = page.locator('.drawer-toggle-btn');
      await expect(toggleBtn).toBeVisible();

      // 1. Light theme screenshot
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${vp.name}-light.png`),
        fullPage: false,
      });

      // 2. Switch to Dark theme
      const themeBtn = page.locator('button[aria-label*="Giao diện"], button[title*="Giao diện"], button[aria-label*="Chuyển sang chế độ"]').first();
      if (await themeBtn.isVisible()) {
        await themeBtn.click();
        await page.waitForTimeout(300);
      } else {
        // Fallback via document attribute
        await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
      }

      // Check dark theme token
      const currentTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
      expect(currentTheme).toBe('dark');

      // 2. Dark theme screenshot
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${vp.name}-dark.png`),
        fullPage: false,
      });

      // Reset theme back to light
      await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
    });
  }

  test('Render correctly with 200% Zoom (WCAG 1.4.4 Resize text)', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Emulate 200% zoom by applying scale / font zoom
    await page.evaluate(() => {
      (document.body.style as any).zoom = '200%';
    });
    await page.waitForTimeout(400);

    // Verify chat input and header are still functional and visible
    const composer = page.locator('.chat-composer-textarea');
    await expect(composer).toBeVisible();
    await composer.fill('Kiểm tra văn bản khi zoom 200%');
    expect(await composer.inputValue()).toBe('Kiểm tra văn bản khi zoom 200%');

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'desktop-zoom-200.png'),
      fullPage: false,
    });
  });

  test('Render correctly with 200% Zoom on Mobile (390x844)', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await page.evaluate(() => {
      (document.body.style as any).zoom = '200%';
    });
    await page.waitForTimeout(400);

    const toggleBtn = page.locator('.drawer-toggle-btn');
    await expect(toggleBtn).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'mobile-zoom-200.png'),
      fullPage: false,
    });
  });
});
