'use strict';
// No analytics, storage of secrets, URL credentials, or private key export.
const q=s=>document.querySelector(s),encoder=new TextEncoder();
let device=null,authorization=null,locked=false;
window.addEventListener('pagehide',()=>{q('#app-secret').value='';authorization=null;});
const encode=buffer=>btoa(String.fromCharCode(...new Uint8Array(buffer))).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
const decode=value=>Uint8Array.from(atob(value.replaceAll('-','+').replaceAll('_','/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));
const canonical=v=>JSON.stringify(Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])));
async function hash(v){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(canonical(v))))].map(x=>x.toString(16).padStart(2,'0')).join('');} // taste-skill-ignore numbering: fixed-width SHA-256 hex, not visual numbering.
function store(mode,callback){return new Promise((resolve,reject)=>{const open=indexedDB.open('mos-trusted-phone',1);open.onupgradeneeded=()=>open.result.createObjectStore('device');open.onerror=()=>reject(Error('裝置儲存無法使用。'));open.onsuccess=()=>{const db=open.result,t=db.transaction('device',mode),request=callback(t.objectStore('device'));request.onerror=()=>reject(Error('裝置儲存失敗。'));t.onabort=()=>{db.close();reject(Error('裝置儲存未完成。'));};t.oncomplete=()=>{resolve(request.result);db.close();};};});}
async function api(path,body,csrf=''){const response=await fetch(path,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});if(!response.ok)throw Error(response.status===404?'管理通道未開放。':'驗證未通過、授權已關閉或管理員未登入。');return response.json();}
async function sign(value){return encode(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},device.key,encoder.encode(canonical(value))));}
function proof(m,nonce,envelopeHash=''){return {action:envelopeHash?'SUBMIT':'AUTHENTICATE',grant_id:m.grant_id,device_id:m.device_id,manifest_hash:authorization.hash,nonce,envelope_hash:envelopeHash};}
function status(value){q('#phone-status').textContent=value;}
async function work(fn){if(locked)return;locked=true;try{await fn();}catch{q('#app-secret').value='';q('#credentials').hidden=true;authorization=null;status('操作未完成。請確認管理員登入、已認證裝置及授權有效期；不要重送不明結果。');}finally{locked=false;}}
q('#enroll-device').onclick=()=>work(async()=>{
 if(await store('readonly',s=>s.get('current')))throw Error('已有裝置，不覆寫');
 const response=await fetch('/ui/admin/status',{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('需要管理員');const admin=await response.json();
 const tenant=q('#tenant').value.trim(),start=await api('/ui/admin/phone-setup/enroll',{tenant_id:tenant},admin.csrf);
 if(start.origin!==location.origin)throw Error('來源不符');
 const pair=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},false,['sign','verify']);
 const pub=encode(await crypto.subtle.exportKey('spki',pair.publicKey));device={key:pair.privateKey,public_key:pub,authority:start.authority,origin:start.origin,device_id:start.device_id,tenant_id:tenant};
 const frame={action:'ENROLL_DEVICE',device_id:start.device_id,nonce:start.nonce,origin:start.origin,public_key:pub,authority:start.authority};
 await api('/ui/admin/phone-setup/enroll/complete',{tenant_id:tenant,device_id:device.device_id,public_key:pub,signature:await sign(frame)},admin.csrf);
 await store('readwrite',s=>s.put(device,'current'));status('已經管理員認證註冊。裝置 ID：'+device.device_id+'。請由受信任管理端簽發指定 App 的短效授權。');
});
q('#verify-device').onclick=()=>work(async()=>{
 device=await store('readonly',s=>s.get('current'));if(!device||device.origin!==location.origin||device.key.extractable)throw Error('未註冊');
 const gid=q('#grant').value.trim(),challenge=await api('/phone-setup/'+encodeURIComponent(gid)+'/challenge',{}),m=challenge.manifest;
 const authority=await crypto.subtle.importKey('spki',decode(device.authority),{name:'ECDSA',namedCurve:'P-256'},false,['verify']);
 if(!await crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},authority,decode(challenge.signature),encoder.encode(canonical(m))))throw Error('公鑰被替換');
 if(m.action!=='THREADS_APP_CREDENTIALS_ONLY'||m.grant_id!==gid||m.device_id!==device.device_id||m.tenant_id!==device.tenant_id||m.origin!==location.origin||Date.parse(m.expires_at)<=Date.now())throw Error('授權不符');
 authorization={manifest:m,hash:await hash(m)};
 await api('/phone-setup/'+gid+'/authenticate',{signature:await sign(proof(m,challenge.nonce))});
 q('#app-id').value=m.app_id;q('#deadline').textContent='期限：'+new Date(m.expires_at).toLocaleString('zh-TW');q('#credentials').hidden=false;status('裝置與指定 App 已驗證。只可傳送一次。');
 setTimeout(()=>{q('#app-secret').value='';q('#credentials').hidden=true;authorization=null;status('授權已到期。');},Math.max(0,Date.parse(m.expires_at)-Date.now()));
});
q('#credentials').onsubmit=e=>{e.preventDefault();work(async()=>{
 const a=authorization;if(!a||Date.parse(a.manifest.expires_at)<=Date.now())throw Error('到期');
 const secret=q('#app-secret').value;q('#app-secret').value='';q('#credentials').hidden=true;
 if(!/^[A-Za-z0-9_-]{8,256}$/.test(secret))throw Error('格式不符');
 const m=a.manifest,gid=m.grant_id,challenge=await api('/phone-setup/'+gid+'/challenge',{});
 if(await hash(challenge.manifest)!==a.hash)throw Error('授權被改寫');
 const symmetric=await crypto.subtle.generateKey({name:'AES-GCM',length:256},true,['encrypt']);
 const publicKey=await crypto.subtle.importKey('spki',decode(m.encryption_key),{name:'RSA-OAEP',hash:'SHA-256'},false,['encrypt']);
 const nonce=crypto.getRandomValues(new Uint8Array(12));
 const ciphertext=await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:encoder.encode(canonical(m))},symmetric,encoder.encode(JSON.stringify({app_id:m.app_id,app_secret:secret})));
 const wrapped=await crypto.subtle.encrypt({name:'RSA-OAEP'},publicKey,await crypto.subtle.exportKey('raw',symmetric));
 const envelope={wrapped_key:encode(wrapped),nonce:encode(nonce),ciphertext:encode(ciphertext)};
 const signature=await sign(proof(m,challenge.nonce,await hash(envelope)));
 authorization=null;
 await api('/phone-setup/'+gid+'/submit',{signature,envelope});status('密文已收妥，本次通道已關閉。等待 Windows DPAPI 確認；這不代表 OAuth 或發布已完成。');
 });};
