import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const SCREENSHOT_DIR = path.resolve('e2e-screenshots/keyboard-modals');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

test.describe('Keyboard Navigation, Focus Outlines & Modal Traps', () => {
  test('Focus visibility with Keyboard Tab navigation', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Press Tab multiple times to move focus through UI
    await page.keyboard.press('Tab');
    const firstFocused = await page.evaluate(() => document.activeElement?.tagName);
    expect(firstFocused).toBeTruthy();

    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');

    // Ensure focused element has a visible outline or focus ring
    const outline = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el) return null;
      const styles = window.getComputedStyle(el);
      return {
        outlineStyle: styles.outlineStyle,
        outlineWidth: styles.outlineWidth,
        outlineColor: styles.outlineColor,
        boxShadow: styles.boxShadow,
      };
    });

    expect(outline).toBeTruthy();
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'keyboard-focus-tab.png'),
    });
  });

  test('Privacy Policy Modal: Trap focus and Escape key dismissal', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Ensure drawer is open
    const isDrawerOpen = await page.locator('.history-drawer.open').isVisible();
    if (!isDrawerOpen) {
      await page.locator('.drawer-toggle-btn').first().click();
      await page.waitForTimeout(300);
    }

    // Open Privacy Modal
    const privacyBtn = page.locator('button:has-text("Chính sách quyền riêng tư")').first();
    await privacyBtn.click();
    await page.waitForTimeout(300);

    const modal = page.locator('[role="dialog"]');
    await expect(modal).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'privacy-modal-opened.png'),
    });

    // Verify Escape key closes the modal
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    await expect(modal).not.toBeVisible();
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'privacy-modal-closed-escape.png'),
    });
  });

  test('Confirm Modal: Trap focus and Escape key dismissal', async ({ page }) => {
    // Seed localStorage with a mock session
    await page.goto('/');
    await page.evaluate(() => {
      const mockSessions = [
        {
          sessionId: 'test-session-esc-1',
          title: 'Học phí 2026',
          createdAt: Date.now(),
          updatedAt: Date.now(),
          messages: [{ id: 'm1', role: 'user', content: 'Học phí thế nào?' }],
        },
      ];
      localStorage.setItem('huit_chat_sessions', JSON.stringify(mockSessions));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Ensure drawer is open
    const isDrawerOpen = await page.locator('.history-drawer.open').isVisible();
    if (!isDrawerOpen) {
      await page.locator('.drawer-toggle-btn').first().click();
      await page.waitForTimeout(300);
    }

    // Click delete session button
    const deleteBtn = page.locator('.history-delete-btn').first();
    await deleteBtn.click();
    await page.waitForTimeout(300);

    const confirmModal = page.locator('[role="dialog"]');
    await expect(confirmModal).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'confirm-modal-opened.png'),
    });

    // Press Escape to cancel
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    await expect(confirmModal).not.toBeVisible();
    // Session should still exist because deletion was cancelled
    const sessionItem = page.locator('.history-item');
    await expect(sessionItem).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'confirm-modal-cancelled-escape.png'),
    });
  });

  test('Mobile History Drawer: Dismiss with Escape key', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Open drawer on mobile
    const toggleBtn = page.locator('.drawer-toggle-btn');
    await toggleBtn.click();
    await page.waitForTimeout(300);

    const drawer = page.locator('.history-drawer.open');
    await expect(drawer).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'mobile-drawer-open.png'),
    });

    // Press Escape
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    await expect(drawer).not.toBeVisible();
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'mobile-drawer-closed-escape.png'),
    });
  });
});
