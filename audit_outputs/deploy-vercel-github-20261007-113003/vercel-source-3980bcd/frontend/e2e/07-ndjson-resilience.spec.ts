import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const SCREENSHOT_DIR = path.resolve('e2e-screenshots/ndjson-resilience');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

test.describe('NDJSON Resilience & Parser Fault-Tolerance', () => {
  test('Handle split chunk across stream buffers without dropping text', async ({ page }) => {
    await page.route('**/api/chat-stream', async (route) => {
      // Chunk 1 has part of the line
      const part1 =
        JSON.stringify({ protocol_version: 2, sequence: 1, type: 'start' }) +
        '\n' +
        '{"protocol_version":2,"sequence":2,"type":"token","payload":{"token":"Trường Đại học ';
      // Chunk 2 completes the line and finishes stream
      const part2 =
        'Công Thương TP.HCM (HUIT)"}}\n' +
        JSON.stringify({ protocol_version: 2, sequence: 3, type: 'text_completed' }) +
        '\n' +
        JSON.stringify({ protocol_version: 2, sequence: 4, type: 'completed' }) +
        '\n';

      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/x-ndjson' },
        body: part1 + part2,
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('.chat-composer-textarea');
    await textarea.fill('Kiểm tra chunk bị cắt đôi');
    await page.keyboard.press('Enter');

    const assistantMsg = page.locator('.message-item.assistant');
    await expect(assistantMsg).toBeVisible();
    await expect(assistantMsg).toContainText('Trường Đại học Công Thương TP.HCM (HUIT)');

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'ndjson-split-chunk-success.png'),
    });
  });

  test('Handle malformed lines and sequence gaps without crashing UI', async ({ page }) => {
    const errorLogs: string[] = [];
    page.on('pageerror', (err) => {
      errorLogs.push(err.message);
    });

    await page.route('**/api/chat-stream', async (route) => {
      const payload = [
        JSON.stringify({ protocol_version: 2, sequence: 1, type: 'start' }) + '\n',
        'THIS IS A MALFORMED CORRUPTED NDJSON LINE {[[[\n',
        JSON.stringify({
          protocol_version: 2,
          sequence: 2,
          type: 'token',
          payload: { token: 'Dữ liệu vẫn được xử lý an toàn.' },
        }) + '\n',
        '{"invalid_field":12345}\n',
        JSON.stringify({
          protocol_version: 2,
          sequence: 5, // Gap: sequence jumps from 2 to 5
          type: 'token',
          payload: { token: ' Dù gặp dòng rác và nhảy sequence.' },
        }) + '\n',
        JSON.stringify({ protocol_version: 2, sequence: 6, type: 'text_completed' }) + '\n',
        JSON.stringify({ protocol_version: 2, sequence: 7, type: 'completed' }) + '\n',
      ].join('');

      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/x-ndjson' },
        body: payload,
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('.chat-composer-textarea');
    await textarea.fill('Kiểm tra dòng rác NDJSON');
    await page.keyboard.press('Enter');

    const assistantMsg = page.locator('.message-item.assistant');
    await expect(assistantMsg).toBeVisible();
    await expect(assistantMsg).toContainText('Dữ liệu vẫn được xử lý an toàn');

    // Page must not crash or throw uncaught fatal errors
    expect(errorLogs.filter((e) => e.includes('Uncaught Error'))).toEqual([]);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'ndjson-malformed-recovery.png'),
    });
  });

  test('Handle duplicate chunks gracefully without duplicating rendered text', async ({ page }) => {
    await page.route('**/api/chat-stream', async (route) => {
      const payload = [
        JSON.stringify({ protocol_version: 2, sequence: 1, type: 'start' }) + '\n',
        JSON.stringify({
          protocol_version: 2,
          sequence: 2,
          type: 'token',
          payload: { token: 'Dòng thông báo duy nhất.' },
        }) + '\n',
        JSON.stringify({
          protocol_version: 2,
          sequence: 2, // Duplicate sequence
          type: 'token',
          payload: { token: 'Dòng thông báo duy nhất.' },
        }) + '\n',
        JSON.stringify({ protocol_version: 2, sequence: 3, type: 'text_completed' }) + '\n',
        JSON.stringify({ protocol_version: 2, sequence: 4, type: 'completed' }) + '\n',
      ].join('');

      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/x-ndjson' },
        body: payload,
      });
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('.chat-composer-textarea');
    await textarea.fill('Kiểm tra trùng lặp chunk');
    await page.keyboard.press('Enter');

    const assistantMsg = page.locator('.message-item.assistant');
    await expect(assistantMsg).toBeVisible();

    // Verify text is present and not duplicated
    const content = await assistantMsg.textContent();
    expect(content).toContain('Dòng thông báo duy nhất.');
    const count = (content?.match(/Dòng thông báo duy nhất\./g) || []).length;
    expect(count).toBe(1);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, 'ndjson-duplicate-handling.png'),
    });
  });
});
