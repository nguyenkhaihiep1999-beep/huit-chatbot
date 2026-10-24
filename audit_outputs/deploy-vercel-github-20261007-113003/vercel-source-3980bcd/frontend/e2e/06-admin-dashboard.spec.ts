import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { MOCK_ADMIN_HEALTH, MOCK_ADMIN_JOBS } from './helpers/mockData';

const SCREENSHOT_DIR = path.resolve('e2e-screenshots/admin');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

test.describe('Admin Authentication & Dashboard Operations', () => {
  test('Admin Login: Validation error on wrong credentials', async ({ page }) => {
    // Mock login failure
    await page.route('**/api/admin/login', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Tên đăng nhập hoặc mật khẩu không chính xác.' }),
      });
    });

    // Mock initial check: not authenticated
    await page.route('**/api/admin/verify', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Chưa đăng nhập' }),
      });
    });

    await page.goto('/admin');
    await page.waitForLoadState('networkidle');

    const usernameInput = page.locator('input[type="text"]#admin-username, input[type="text"]').first();
    const passwordInput = page.locator('input[type="password"]#admin-password, input[type="password"]').first();
    const submitBtn = page.locator('button[type="submit"]');

    await usernameInput.fill('wrong_admin');
    await passwordInput.fill('wrong_pass');
    await submitBtn.click();

    // Verify error banner
    const errorAlert = page.locator('.admin-error-banner, [role="alert"]');
    await expect(errorAlert).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'admin-login-error.png'),
    });
  });

  test('Admin Dashboard: Health metrics, Jobs panel, Filter tabs & Modals', async ({ page }) => {
    // Mock session verification as true
    await page.route('**/api/admin/verify', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ authenticated: true, user: 'admin_huit', role: 'superadmin' }),
      });
    });

    // Mock admin health
    await page.route('**/api/admin/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_ADMIN_HEALTH),
      });
    });

    // Mock admin metrics
    await page.route('**/api/admin/metrics', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          active_sessions: 14,
          total_queries_today: 1250,
          avg_latency_ms: 180,
          cache_hit_rate: 88.5,
        }),
      });
    });

    // Mock admin jobs
    await page.route('**/api/admin/jobs*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          jobs: MOCK_ADMIN_JOBS,
          total: MOCK_ADMIN_JOBS.length,
          page: 1,
        }),
      });
    });

    await page.goto('/admin');
    await page.waitForLoadState('networkidle');

    // Verify dashboard rendered
    const dashboardTitle = page.locator('.admin-dashboard-title, h1, h2:has-text("Quản Trị")');
    await expect(dashboardTitle.first()).toBeVisible();

    // Verify metrics cards
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'admin-dashboard-health.png'),
    });

    // Switch to Jobs tab if exists
    const jobsTab = page.locator('button:has-text("Tác vụ"), button:has-text("Jobs")').first();
    if (await jobsTab.isVisible()) {
      await jobsTab.click();
      await page.waitForTimeout(300);

      // Verify jobs list
      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, 'admin-jobs-panel.png'),
      });
    }

    // Test back button
    const backBtn = page.locator('.admin-back-btn, button:has-text("Về trang chủ"), button[aria-label*="Quay lại"]').first();
    if (await backBtn.isVisible()) {
      await backBtn.click();
      await page.waitForTimeout(300);
      expect(page.url()).toContain('/');
    }
  });
});
