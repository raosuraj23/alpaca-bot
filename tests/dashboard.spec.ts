import { test, expect } from '@playwright/test';

test.describe('Automated Bot Terminal Verification', () => {

  test('Multi-Agent tabs and global header render successfully', async ({ page }) => {
    await page.goto('/');

    // Verify application header
    await expect(page.locator('text=ALPACA X')).toBeVisible();

    // Verify Tab routing
    await expect(page.locator('text=Desk')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Analysis' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Bots' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Ledger' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Brain' })).toBeVisible();
  });

  test('Orchestrator Sandbox FAB triggers successfully', async ({ page }) => {
    await page.goto('/');

    // FAB Button is positioned fixed at bottom right
    const orchestratorFab = page.locator('button').locator('.rounded-full').first();
    await expect(page.locator('button.fixed.bottom-6.right-6')).toBeVisible();
  });

  test('Analytical views load without crushing bounds', async ({ page }) => {
    await page.goto('/');
    
    // Tap the Analysis tab
    await page.getByRole('button', { name: 'Analysis' }).click();
    
    // Validate the Analytics dashboard loaded correctly
    await expect(page.locator('text=Equity Curve')).toBeVisible();
    await expect(page.locator('text=Core Formulas')).toBeVisible();
  });

  test('Analysis charts render with valid bounds and no zero-size warnings', async ({ page }) => {
    const messages: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'warning' || msg.type() === 'error') {
        messages.push(msg.text());
      }
    });

    await page.goto('/');
    await page.getByRole('button', { name: 'Analysis' }).click();

    await expect(page.locator('text=Return Distribution')).toBeVisible();
    await expect(page.locator('text=LLM Telemetry').first()).toBeVisible();
    await expect(page.locator('text=Equity Curve')).toBeVisible();

    await page.waitForTimeout(500);
    expect(messages).not.toContainEqual(expect.stringContaining('The width(-1) and height(-1) of chart should be greater than 0'));
  });

});
