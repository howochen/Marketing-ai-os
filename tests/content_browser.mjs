// Synthetic content only, actual DOM clicks through the existing cookie/CSRF UI.
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const {Browser,sleep}=await import(pathToFileURL(`${process.argv[2]}/scripts/lib/cdp.mjs`));
const {probe,layout,app:appProbe}=await import(pathToFileURL(`${process.argv[2]}/scripts/lib/probe.mjs`));
const {judge,judgeLayout,judgeApp,APP_SKIP}=await import(pathToFileURL(`${process.argv[2]}/scripts/lib/rules.mjs`));
const {tenant_id}=JSON.parse(readFileSync('.content-test/browser-access.json','utf8'));
const challengeResponse=await fetch('http://127.0.0.1:8892/admin/login-challenges',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Key':'test-admin-key-at-least-thirty-characters'},body:JSON.stringify({tenant_id,subject:'offline-browser-owner'})});
assert.equal(challengeResponse.ok,true);const {token:challenge}=await challengeResponse.json();
const browser=await Browser.launch();
const evidence={engine:'Chromium; iPhone viewport, not physical Safari',http_database_flow:true,widths:[1440,768,390],real_ai_calls:0,real_social_posts:0};
try{
 const page=await browser.newPage({width:390,height:844,mobile:true});
 await page.goto('http://127.0.0.1:8892/app/content');
 async function wait(selector){for(let i=0;i<60;i++){if(await page.eval(s=>!!document.querySelector(s),selector))return;await sleep(100);}throw Error('Missing UI '+selector);}
 async function click(selector){await wait(selector);const point=await page.eval(s=>{const e=document.querySelector(s);e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};},selector);await page.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});await page.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});await sleep(250);}
 async function fill(selector,value){await page.eval(({selector,value})=>{const e=document.querySelector(selector);e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));},{selector,value});}
 await wait('#login-form');await fill('#login-value',challenge);await click('#login-form button');
 await wait('#new-content');await click('#new-content');await wait('#brief-form');
 for(const [selector,value] of Object.entries({'#brand':'合成茶室','#topic':'午後慢慢喝台灣茶','#description':'以台灣茶為主的合成餐飲品牌，僅供離線內容驗收。','#audience':'喜歡台灣茶的上班族','#goal':'邀請讀者認識茶款','#tone':'自然親切','#required-terms':'台灣茶','#forbidden-terms':'神藥'}))await fill(selector,value);
 await page.eval(()=>{document.querySelector('#industry').value='food';});
 await click('#brief-form button[type=submit]');await wait('#draft-form');
 const initial='午後想喝點什麼？台灣茶陪你慢慢喝。留言聊聊你喜歡的茶。';
 await fill('#draft-text',initial);await fill('#hook','不在全文的 Hook');await fill('#cta','留言聊聊你喜歡的茶。');
 await click('#draft-form button[type=submit]');await wait('#approve-revision');
 assert.equal(await page.eval(()=>document.querySelector('#approve-revision').disabled),true);
 assert.equal(await page.eval(()=>document.querySelector('#checks').textContent.includes('FAIL')),true);
 await fill('#hook','午後想喝點什麼？');await fill('#reason','修正 Hook，與全文保持一致');await click('#draft-form button[type=submit]');
 for(let i=0;i<60;i++){if(await page.eval(()=>document.querySelector('#approve-revision')&&!document.querySelector('#approve-revision').disabled))break;await sleep(100);}
 assert.equal(await page.eval(()=>document.querySelector('#checks').textContent.includes('UNEVALUATED')),true);
 await click('#approve-revision');await wait('#plan-form');
 await fill('#planned-at','2090-06-18T14:30');await fill('#plan-note','合成內容演練，不會自動發布');await click('#plan-form button');
 for(let i=0;i<60;i++){if(await page.eval(()=>document.querySelector('#plan-list').textContent.includes('等待帳號連接')))break;await sleep(100);}
 assert.equal(await page.eval(()=>document.querySelector('#plan-list').textContent.includes('等待帳號連接')),true);
 mkdirSync('docs/content/screens',{recursive:true});
 const measurements=[];
 for(const width of evidence.widths){await page.setViewport({width,height:900,mobile:width===390});await page.eval(()=>scrollTo(0,0));assert.equal(await page.eval(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:`docs/content/screens/workbench-${width}.png`,format:'png',fullPage:true});await page.screenshot({path:`docs/content/screens/fold-${width}.png`,format:'png'});const m=await page.eval(probe),l=await page.eval(layout),a=await page.eval(appProbe);measurements.push({width,findings:[...[...judge(m,{width}),...judgeLayout(l,{width})].filter(f=>!APP_SKIP.has(f.id)&&!['no-title','small-title'].includes(f.id)),...judgeApp(a,m,{width})]});}
 writeFileSync('docs/content/workbench-inspect.json',JSON.stringify(measurements,null,2)+'\n');
 await page.setViewport({width:390,height:844,mobile:true});
 await page.eval(()=>document.querySelector('#editor').scrollIntoView({block:'start'}));
 await page.screenshot({path:'docs/content/screens/mobile-editor.png',format:'png'});
 await fill('#draft-text',initial+'今天也慢慢喝。');await fill('#reason','人工增加結尾並重新審核');await click('#draft-form button[type=submit]');
 await wait('#approve-revision');assert.equal(await page.eval(()=>document.querySelector('#plan-list').textContent.includes('需重新核准')),true);
 await click('#compare');assert.equal(await page.eval(()=>document.querySelector('#comparison').textContent.includes('今天也慢慢喝。')),true);
 await click('[data-restore]');assert.equal(await page.eval(()=>document.querySelector('#draft-text').value),initial);
 await click('#draft-form button[type=submit]');await sleep(500);
 assert.equal(await page.eval(()=>document.querySelectorAll('.revision-list li').length),4);
 // Force a server conflict; the unsaved text must stay in the editor.
 await fill('#draft-text',initial+'保留未儲存內容。');await fill('#reason','驗證錯誤不會遺失文字');
 await page.eval(()=>{window.actualFetch=fetch;window.fetch=async(path,...args)=>String(path).endsWith('/revisions')&&args[0]?.method==='POST'?new Response(JSON.stringify({detail:'Revision parent is stale'}),{status:409,headers:{'Content-Type':'application/json'}}):window.actualFetch(path,...args);});
 await click('#draft-form button[type=submit]');assert.equal(await page.eval(()=>document.querySelector('#draft-text').value.includes('保留未儲存內容')),true);
 assert.equal(await page.eval(()=>document.querySelector('#message').textContent.includes('您的文字仍保留')),true);
 await page.eval(()=>{window.fetch=window.actualFetch;});
 assert.deepEqual(page.consoleErrors,[]);
 evidence.qa_fail_blocks_approval=true;evidence.manual_revision_approval_plan=true;evidence.new_revision_invalidates_approval=true;evidence.restore_creates_new_revision=true;evidence.conflict_preserves_unsaved_text=true;evidence.horizontal_overflow=false;evidence.console_errors=0;
 writeFileSync('docs/content/browser.json',JSON.stringify(evidence,null,2)+'\n');console.log('Content workbench browser flow: PASS');
}finally{await browser.close();}
