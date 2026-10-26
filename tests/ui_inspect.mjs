// Authenticate through the actual form before the external design inspector opens its pages.
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const skill=process.argv[2], target=process.argv[3]||'http://127.0.0.1:8787/app';
const {Browser,sleep}=await import(pathToFileURL(`${skill}/scripts/lib/cdp.mjs`));
const launch=Browser.launch.bind(Browser);
Browser.launch=async options=>{
 const browser=await launch(options),p=await browser.newPage();
 const data=JSON.parse(readFileSync('.ui-preview/access.json','utf8'));
 await p.goto('http://127.0.0.1:8787/app');
 await p.eval(value=>{document.querySelector('#login-value').value=value;document.querySelector('#login-form').requestSubmit();},data.challenge);
 await sleep(1200);await p.close();return browser;
};
process.argv=['node','inspect.mjs',target,'--app','--out','docs/pub002/inspect'];
await import(pathToFileURL(`${skill}/scripts/inspect.mjs`));
