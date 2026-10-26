// Offline browser smoke test; the preview server bans real provider transports.
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const skill=process.argv[2];
const {Browser,sleep}=await import(pathToFileURL(`${skill}/scripts/lib/cdp.mjs`));
const data=JSON.parse(readFileSync('.ui-preview/access.json','utf8'));
const browser=await Browser.launch();
try {
 const p=await browser.newPage({width:1440,height:900});
 await p.goto('http://127.0.0.1:8787/app');
 await p.eval(value=>{document.querySelector('#login-value').value=value;document.querySelector('#login-form').requestSubmit();},data.challenge);
 await sleep(1800);
 assert.match(await p.eval(()=>document.body.innerText),/青禾品牌/);
 assert.equal(await p.eval(()=>document.cookie.includes('mos_ui_session')),false);
 mkdirSync('docs/pub002/screens',{recursive:true});
 const results=[];
 for(const route of ['','threads','publications','admin']) {
  await p.goto(`http://127.0.0.1:8787/app/${route}`);
  if(route==='admin') {
   await p.eval(value=>{document.querySelector('#login-value').value=value;document.querySelector('#login-form').requestSubmit();},data.admin_secret);
   await sleep(1200);
  }
  for(const width of [1440,768,390]) {
   await p.setViewport({width,height:900});await sleep(300);
   const measure=await p.eval(()=>({title:document.querySelector('h1')?.innerText,overflow:document.documentElement.scrollWidth>innerWidth,cookie:document.cookie}));
   assert.ok(measure.title);assert.equal(measure.overflow,false,`${route} ${width} overflow`);
   await p.screenshot({path:`docs/pub002/screens/${route||'home'}-${width}.png`,format:'png',fullPage:true});
   results.push({route:route||'home',width,title:measure.title,overflow:measure.overflow});
  }
 }
 await p.goto('http://127.0.0.1:8787/app/publications');
 await p.eval(()=>document.querySelector('[data-preview]').click());await sleep(300);
 assert.match(await p.eval(()=>document.body.innerText),/確認發布版本/);
 await p.screenshot({path:'docs/pub002/screens/confirmation-390.png',format:'png',fullPage:true});
 writeFileSync('docs/pub002/browser.json',JSON.stringify({mode:'SYNTHETIC_ONLY',results,previewVerified:true,realProviderCalls:0},null,2)+'\n');
 console.log('Browser smoke: 12 responsive views and immutable preview passed; no publication triggered.');
} finally {await browser.close();}
