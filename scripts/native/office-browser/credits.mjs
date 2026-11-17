/** Build-time license capture only; never part of the Python product runtime. */
import fs from 'node:fs';import path from 'node:path';import {pathToFileURL} from 'node:url';
const source=path.resolve(process.argv[2]),root=path.resolve(process.argv[3]);
const {chromium}=await import(pathToFileURL(path.join(source,'node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs')));
const browser=await chromium.launch({executablePath:path.join(root,'browser/chrome.exe'),headless:false,
 args:['--headless=chrome','--disable-background-networking','--disable-extensions','--disable-sync']});
try{
 const version=await(await browser.newBrowserCDPSession()).send('Browser.getVersion');
 const page=await browser.newPage();await page.goto('chrome://credits/');
 const text=await page.locator('body').textContent();
 fs.writeFileSync(path.join(root,'browser/CHROMIUM-THIRD-PARTY-LICENSES.txt'),text+'\n');
 console.log(JSON.stringify({version,licenseBytes:Buffer.byteLength(text+'\n')}));
}finally{await browser.close();}
