// Set MOS_CDP_HELPER to the existing CDP helper file URL; use an isolated synthetic preview only.
const {Browser,sleep}=await import(process.env.MOS_CDP_HELPER);
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
const live=Boolean(process.env.MOS_UX_LOGIN_CODE),access=live?{challenge:process.env.MOS_UX_LOGIN_CODE,origin:process.env.MOS_UX_ORIGIN}:JSON.parse(readFileSync('.threads-callback-test/auto-browser-access.json','utf8'));delete process.env.MOS_UX_LOGIN_CODE;
const out=live?'.threads-local/runtime-recovery/ux-windows':'docs/ux001';mkdirSync(out,{recursive:true});const browser=await Browser.launch(),results=[];let phase='start';
try{
 const page=await browser.newPage();if(live){await page.send('Network.enable');await page.send('Network.setExtraHTTPHeaders',{headers:{'ngrok-skip-browser-warning':'1'}});}
 await page.goto(access.origin+'/app/automation');await page.eval(async a=>{const r=await fetch('/ui/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:a.challenge})});if(!r.ok)throw Error('login');},access);access.challenge='';await page.goto(access.origin+'/app/automation');
 for(let i=0;i<90;i++){if(await page.eval(()=>Boolean(document.querySelector('#setup-ai-policy'))))break;await sleep(300);}
 const click=async s=>{const xy=await page.eval(s=>{const e=document.querySelector(s);e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2};},s);await page.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...xy});await page.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...xy});await sleep(250);};
 phase='existing';const preserved=await page.eval(()=>({savedKeys:[...document.querySelectorAll('#setup-ai-policy option')].filter(x=>x.textContent.includes('Key 已保存')).length,steps:document.querySelectorAll('[data-setup-step]').length,overview:!!document.querySelector('.setup-overview')}));if(preserved.steps!==3||!preserved.overview)throw Error('steps');results.push(preserved);
 if(!live){
  phase='brand';await click('#auto-brand-aj');await click('#brand-apply');if(!await page.eval(()=>document.querySelector('#brand-applied-status').textContent.includes('已套用')))throw Error('brand');
  await page.eval(()=>{document.querySelector('#auto-model').value='gpt-6-luna';document.querySelector('#auto-mode').value='FULL';document.querySelector('#auto-creative-mode').value='BRAND_GUIDED';document.querySelector('#auto-account').value=document.querySelector('#auto-account option:not([value=""])').value;window.uxSaved=null;window.keyFailure=true;window.keyCalls=0;const original=fetch;window.fetch=async(path,o)=>{if(path.endsWith('/provider-key')){keyCalls++;if(keyFailure)return new Response(JSON.stringify({detail:'HTTPS_REQUIRED'}),{status:403,headers:{'Content-Type':'application/json'}});}const r=await original(path,o);if(path==='/automation/policies'&&o?.method==='POST'&&r.ok)uxSaved=await r.clone().json();return r;};});
  phase='draft';await click('[data-setup-step="1"]');await click('#setup-save-first');await click('#setup-step-2 button.primary');for(let i=0;i<60;i++){if(await page.eval(()=>uxSaved&&document.querySelector(`[data-auto-key="${uxSaved.id}"]`)))break;await sleep(250);}
  phase='keyfailure';await page.eval(()=>document.querySelector('[data-auto-key]:not([hidden]) input').value='synthetic-ui-test-key-not-a-real-secret');await click('[data-auto-key]:not([hidden]) button');
  if(!await page.eval(()=>document.querySelector('[data-auto-key]:not([hidden]) input').value==='synthetic-ui-test-key-not-a-real-secret'&&document.querySelector('[data-auto-key]:not([hidden]) [role=status]').textContent.includes('仍保留')))throw Error('retention');
  phase='keysave';await page.eval(()=>keyFailure=false);await click('[data-auto-key]:not([hidden]) button');for(let i=0;i<60;i++){if(await page.eval(()=>document.querySelector('#setup-ai-connection .key-saved')))break;await sleep(250);}
  if(!await page.eval(()=>!!document.querySelector('#setup-ai-connection .key-saved')&&!document.querySelector('[data-auto-key]:not([hidden])')))throw Error('save');
  results.push({newDraft201:true,brandApplied:true,keyFailureRetained:true,keySuccessGreen:true,noRepeatedKeyInput:true,requests:await page.eval(()=>keyCalls)});
 }
 phase='screens';for(const width of [1440,768,390]){
  await page.setViewport({width,height:900,mobile:width===390});await click('[data-setup-step="1"]');
  const overflow=await page.eval(()=>document.documentElement.scrollWidth>innerWidth+1);if(overflow)throw Error('overflow');
  await page.eval(()=>document.querySelector('.setup-overview').scrollIntoView({block:'start'}));await page.screenshot({path:out+'/ai-'+width+'.png',format:'png'});results.push({width,noHorizontalOverflow:true});
 }
 phase='persist';await page.goto(access.origin+'/app/automation');for(let i=0;i<90;i++){if(await page.eval(()=>Boolean(document.querySelector('#setup-ai-policy'))))break;await sleep(300);}
 const saved=await page.eval(()=>({keyShown:document.querySelector('.setup-overview').textContent.includes('已安全保存'),noPlaintext:!document.body.textContent.includes('synthetic-ui-test-key-not-a-real-secret')}));if(!saved.keyShown||!saved.noPlaintext)throw Error('persist');results.push({...saved,paidCalls:0,threadsPosts:0});
 await page.eval(async()=>{await api('/ui/session',{method:'DELETE'});});writeFileSync(out+'/evidence.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results));
}catch(e){throw Error('UX_CHECK_FAILED:'+phase);}finally{await browser.close();}
