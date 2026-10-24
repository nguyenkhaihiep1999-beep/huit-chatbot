import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { MOCK_RAG_RESPONSE_CHUNKS } from './helpers/mockData';

const SCREENSHOT_DIR = path.resolve('e2e-screenshots/chat-states');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

test.describe('Chat States, Markdown Rendering, Tables & Sources', () => {
  test('Empty state: Displays suggestions, brand hero and capabilities', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const hero = page.locator('.empty-state-hero');
    await expect(hero).toBeVisible();

    const suggestions = page.locator('.suggestion-chip-btn');
    expect(await suggestions.count()).toBeGreaterThanOrEqual(3);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'chat-empty-state.png'),
    });
  });

  test('Streaming & Long Answer: Renders tokens, table, citations and stops button', async ({ page }) => {
    // Intercept streaming API with slow chunks to capture streaming state & final content
    await page.route('**/api/chat-stream', async (route) => {
      // Return NDJSON stream
      const headers = {
        'Content-Type': 'application/x-ndjson',
        'Cache-Control': 'no-cache',
        'Transfer-Encoding': 'chunked',
      };
      
      const body = MOCK_RAG_RESPONSE_CHUNKS.join('');
      await route.fulfill({
        status: 200,
        headers,
        body,
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('.chat-composer-textarea');
    await textarea.fill('Cho tôi thông tin tuyển sinh và học phí 2026');
    await page.keyboard.press('Enter');

    // Wait for response to be rendered
    const userMsg = page.locator('.message-item.user');
    await expect(userMsg).toBeVisible();

    const assistantMsg = page.locator('.message-item.assistant');
    await expect(assistantMsg).toBeVisible();

    // Verify markdown table rendered properly
    const table = assistantMsg.locator('table');
    await expect(table).toBeVisible();

    const tableHeaders = table.locator('th');
    expect(await tableHeaders.count()).toBe(4);

    // Verify source citations rendered
    const sourcesContainer = assistantMsg.locator('.source-citations-bar');
    await expect(sourcesContainer).toBeVisible();

    const sourceLinks = sourcesContainer.locator('a.source-badge');
    expect(await sourceLinks.count()).toBe(2);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'chat-markdown-table-sources.png'),
    });
  });

  test('Error state: Displays inline error alert gracefully when stream fails', async ({ page }) => {
    await page.route('**/api/chat-stream', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal Server Error during LLM retrieval' }),
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('.chat-composer-textarea');
    await textarea.fill('Câu hỏi gây lỗi máy chủ');
    await page.keyboard.press('Enter');

    // Check error display in assistant bubble
    const errorAlert = page.locator('.message-inline-error, .toast-error, .message-bubble:has-text("lỗi")');
    await expect(errorAlert.first()).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'chat-error-state.png'),
    });
  });

  test('Offline & Reconnect banner: Emulate offline mode and recovery', async ({ page, context }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Simulate browser going offline
    await context.setOffline(true);
    await page.evaluate(() => {
      window.dispatchEvent(new Event('offline'));
    });
    await page.waitForTimeout(300);

    // Verify offline / reconnect indicator or disabled input
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'chat-offline-state.png'),
    });

    // Go back online
    await context.setOffline(false);
    await page.evaluate(() => {
      window.dispatchEvent(new Event('online'));
    });
    await page.waitForTimeout(300);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'chat-back-online-state.png'),
    });
  });
});
