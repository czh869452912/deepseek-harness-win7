export function credentialFreeEnvironment(environment) {
  return Object.fromEntries(Object.entries(environment).filter(([name]) =>
    !/(?:^|_)(?:API_KEY|API_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|OAUTH_TOKEN)$/i.test(name)
    && !/^(?:DSH_HOME|PYTHONPATH|PYTHONHOME)$/i.test(name)));
}

export async function reloadOriginalPage(connection, waitFor, parameters = {}) {
  const previous = await connection.evaluate('performance.timeOrigin');
  await connection.call('Page.reload', parameters);
  await waitFor(() => connection.evaluate('performance.timeOrigin !== ' + JSON.stringify(previous)),
    'new document after original page reload');
}

export async function closeOriginalBrowser(connection, browser, waitFor) {
  if (connection && connection.socket.readyState === 1) {
    try { await connection.call('Browser.close'); }
    catch (error) { if (connection.socket.readyState !== 3) throw error; }
    await waitFor(() => connection.socket.readyState === 3, 'original browser protocol disconnected');
  }
  if (browser?.exitCode === null) {
    try { await waitFor(() => browser.exitCode !== null || browser.signalCode !== null, 'browser launcher exited'); }
    catch (error) {
      browser.kill();
      await waitFor(() => browser.exitCode !== null || browser.signalCode !== null, 'browser launcher terminated');
      throw error;
    }
  }
}

export async function deferProviderOnboarding(connection, waitFor, required = true) {
  const dialog = '[role="dialog"][aria-label="Add an API key to get started"], [role="dialog"][aria-label="添加一个 API Key 开始使用"]';
  const point = await waitFor(() => connection.evaluate(`(() => {
    const dialog = document.querySelector(${JSON.stringify(dialog)});
    if (!dialog) return ${required ? 'false' : 'document.getElementById("root")?.inert === false && {absent: true}'};
    const button = Array.from(dialog.querySelectorAll('button')).find(element =>
      ['Configure later', '稍后配置'].includes(element.textContent.trim()));
    if (!button || button.disabled) return false;
    const bounds = button.getBoundingClientRect();
    const pointX = bounds.x + bounds.width / 2, pointY = bounds.y + bounds.height / 2;
    return bounds.width && bounds.height && button.contains(document.elementFromPoint(pointX, pointY)) && {x: pointX, y: pointY};
  })()`), 'original provider onboarding defer button');
  if (point.absent) return false;
  await connection.call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
  await connection.call('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
  await waitFor(() => connection.evaluate(`!document.querySelector(${JSON.stringify(dialog)})
    && document.getElementById('root')?.inert === false`), 'provider onboarding dismissed and application interactive');
  return true;
}
