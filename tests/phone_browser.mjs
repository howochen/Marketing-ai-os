// Offline integration: no screenshots after a credential field is populated.
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const {Browser,sleep}=await import(pathToFileURL(`${process.argv[2]}/scripts/lib/cdp.mjs`));
const {tenant_id}=JSON.parse(readFileSync('.phone-setup-test/access.json','utf8'));
const b=await Browser.launch();
try{
 const p=await b.newPage({width:1440,height:900});await p.goto('http://127.0.0.1:8891/app/phone-setup');
 mkdirSync('docs/phone-setup/screens',{recursive:true});
 for(const width of [1440,768,390]){
  await p.setViewport({width,height:900});
  assert.equal(await p.eval(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.equal(await p.eval(()=>document.querySelector('#app-secret').value===''),true);
  await p.screenshot({path:`docs/phone-setup/screens/empty-${width}.png`,format:'png',fullPage:true});
 }
 // Root authentication is the existing offline test credential, not a new login UI.
 assert.equal(await p.eval(async()=>{const r=await fetch('/ui/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret:'test-admin-key-at-least-thirty-characters'})});return r.ok;}),true);
 await p.eval(tid=>{document.querySelector('#tenant').value=tid;document.querySelector('#enroll-device').click();},tenant_id);
 await sleep(700);
 assert.equal(await p.eval(async()=>{const d=await store('readonly',s=>s.get('current'));if(!d||d.key.extractable)return false;try{await crypto.subtle.exportKey('pkcs8',d.key);return false;}catch{return true;}}),true);
 const gid=await p.eval(async()=>{const d=await store('readonly',s=>s.get('current'));const r=await fetch('/__offline/authorize',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Key':'test-admin-key-at-least-thirty-characters'},body:JSON.stringify({device_id:d.device_id})});if(!r.ok)throw Error('Offline authorization failed');return (await r.json()).grant_id;});
 await p.eval(id=>{globalThis.originalFetch=window.fetch;window.fetch=async(...args)=>{const response=await originalFetch(...args);if(String(args[0])==='/phone-setup/'+id+'/challenge'){const value=await response.json();value.manifest.encryption_key='substituted-key';return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});}return response;};document.querySelector('#grant').value=id;document.querySelector('#verify-device').click();},gid);await sleep(500);
 assert.equal(await p.eval(()=>document.querySelector('#credentials').hidden),true);
 await p.eval(()=>{window.fetch=globalThis.originalFetch;});
 await p.eval(id=>{document.querySelector('#grant').value=id;document.querySelector('#verify-device').click();},gid);await sleep(700);
 assert.equal(await p.eval(()=>document.querySelector('#credentials').hidden),false);
 // Do not capture or print the DOM, network body, secret, or screenshot from here onward.
 await p.eval(()=>{document.querySelector('#app-secret').value='synthetic-browser-only-value';document.querySelector('#credentials').requestSubmit();});await sleep(700);
 assert.equal(await p.eval(()=>document.querySelector('#app-secret').value===''),true);
 assert.equal(await p.eval(()=>document.querySelector('#phone-status').textContent.includes('密文已收妥')),true);
 const result=await p.eval(async id=>{const r=await fetch('/__offline/apply/'+id,{method:'POST',headers:{'X-Admin-Key':'test-admin-key-at-least-thirty-characters'}});if(!r.ok)throw Error('Offline DPAPI apply failed');return r.json();},gid);
 assert.equal(result.applied,true);assert.equal(result.existing_keys_preserved,true);
 writeFileSync('docs/phone-setup/browser.json',JSON.stringify({...result,private_key_export_rejected:true,key_substitution_rejected:true,viewport_widths:[1440,768,390],screenshots:'empty fields only; none after secret input'},null,2)+'\n');
 console.log('Offline browser crypto, registered-device authentication, encrypted submission and DPAPI: PASS');
}finally{await b.close();}
