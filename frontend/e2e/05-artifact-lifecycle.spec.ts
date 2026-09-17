import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { MOCK_RAG_RESPONSE_CHUNKS } from './helpers/mockData';

const SCREENSHOT_DIR = path.resolve('e2e-screenshots/artifacts');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

test.describe('Artifact Lifecycle: Preview, Lightbox, Export & Upscale', () => {
  test('Render artifact card and open Lightbox modal', async ({ page }) => {
    // Intercept chat stream to deliver artifact
    await page.route('**/api/chat-stream', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/x-ndjson' },
        body: MOCK_RAG_RESPONSE_CHUNKS.join(''),
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('.chat-composer-textarea');
    await textarea.fill('Xem biểu đồ tuyển sinh');
    await page.keyboard.press('Enter');

    // Wait for artifact card
    const artifactCard = page.locator('.artifact-card');
    await expect(artifactCard).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'artifact-card-rendered.png'),
    });

    // Click to open preview lightbox
    const previewBtn = artifactCard.locator('button:has-text("Xem chi tiết"), button[title*="Xem"], .artifact-preview-box, .btn-artifact-view').first();
    await previewBtn.click();
    await page.waitForTimeout(300);

    // Lightbox modal should be open
    const lightbox = page.locator('.artifact-lightbox-backdrop, .visual-lightbox-overlay, [role="dialog"]');
    await expect(lightbox.first()).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'artifact-lightbox-opened.png'),
    });

    // Close lightbox via Escape key
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'artifact-lightbox-closed.png'),
    });
  });

  test('Artifact Export options menu and trigger', async ({ page }) => {
    await page.route('**/api/chat-stream', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/x-ndjson' },
        body: MOCK_RAG_RESPONSE_CHUNKS.join(''),
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('.chat-composer-textarea');
    await textarea.fill('Tải dữ liệu');
    await page.keyboard.press('Enter');

    const artifactCard = page.locator('.artifact-card');
    await expect(artifactCard).toBeVisible();

    // Find export/download trigger
    const exportBtn = artifactCard.locator('button[aria-label*="Tải"], button:has-text("Tải"), .btn-artifact-action').first();
    if (await exportBtn.isVisible()) {
      await exportBtn.click();
      await page.waitForTimeout(200);

      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, 'artifact-export-menu.png'),
      });
    }
  });
});
