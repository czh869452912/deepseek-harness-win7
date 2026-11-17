/** Current original account entry -> API-key editor -> explicit defer action. */
import {deferProviderOnboarding} from './browser_onboarding.mjs';

export async function deferCurrentProviderOnboarding(connection, waitFor) {
  const point = await waitFor(() => connection.evaluate(`(() => {
    const editor = document.querySelector('[role="dialog"][aria-label="Add an API key to get started"]');
    if (editor) return {editor: true};
    const dialog = document.querySelector('[role="dialog"][aria-label="Get started"]');
    const button = dialog && Array.from(dialog.querySelectorAll('button')).find(row => row.textContent.trim() === 'Add API Key');
    if (!button || button.disabled) return false;
    const bounds = button.getBoundingClientRect(), x = bounds.x + bounds.width / 2, y = bounds.y + bounds.height / 2;
    return bounds.width && bounds.height && button.contains(document.elementFromPoint(x, y)) && {x, y};
  })()`), 'current original account onboarding API-key action');
  if (!point.editor) {
    await connection.call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
    await connection.call('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
  }
  return deferProviderOnboarding(connection, waitFor);
}

export async function deferCurrentProviderWithPlaywright(page) {
  const start = page.getByRole('dialog', {name: /^(Get started|开始使用)$/});
  const editor = page.getByRole('dialog', {name: /^(Add an API key to get started|添加一个 API Key 开始使用)$/});
  await page.waitForFunction(() => Array.from(document.querySelectorAll('[role="dialog"]')).some(row =>
    ['Get started', '开始使用', 'Add an API key to get started', '添加一个 API Key 开始使用'].includes(row.getAttribute('aria-label'))));
  if (await start.isVisible()) await start.getByRole('button', {name: /^(Add API Key|添加 API Key)$/}).click();
  await editor.getByRole('button', {name: /^(Configure later|稍后配置)$/}).click();
  await editor.waitFor({state: 'hidden'});
}
