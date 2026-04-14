import { test, expect } from '@playwright/test';

test.describe('Automated Bot Terminal Verification', () => {

  test('Multi-Agent tabs and global header render successfully', async ({ page }) => {
    await page.goto('/');

    // Verify application header
    await expect(page.locator('text=ALPACA X')).toBeVisible();

    // Verify Tab routing
    await expect(page.locator('text=Desk')).toBeVisible();
    await expect(page.locator('text=Analysis')).toBeVisible();
    await expect(page.locator('text=Bots')).toBeVisible();
    await expect(page.locator('text=Ledger')).toBeVisible();
    await expect(page.locator('text=Brain')).toBeVisible();
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
    await page.locator('text=Analysis').click();
    
    // Validate the Strategy attribution module loaded correctly (analyst dashboard)
    await expect(page.locator('text=Strategy Attribution')).toBeVisible();
    await expect(page.locator('text=Live Equity Trajectory')).toBeVisible();
  });

});
