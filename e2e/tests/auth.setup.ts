import { test as setup } from '@playwright/test';

const authFile = 'e2e/.auth/user.json';

/**
 * SQLTexter has no login: every browser is the same implicit local user.
 *
 * The specs still load a storage-state file, so this writes an empty one rather
 * than touching every spec.
 */
setup('write empty browser state', async ({ page }) => {
  await page.context().storageState({ path: authFile });
});
