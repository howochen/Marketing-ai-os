'use strict';
const GoogleOAuthUI=(()=>{
 const json=body=>({method:'POST',body:JSON.stringify(body)});
 async function mount(host,policy,describe){
  const box=document.createElement('section');box.className='panel';host.append(box);const base='/automation/policies/'+policy.id;
  const state=await api(base+'/google-status');
  box.innerHTML=`<h4>連接 Google，確認 Gemini 免費資格</h4><p>只需在 Google 官方畫面登入並同意唯讀授權。MOS 會自動讀取專案、核對已保存的 Gemini Key 與免費資格，並安全維護授權；不用複製任何 Token。</p>
   <p id="google-connection-status" role="status"></p>${state.client_configured?'':`<p class="notice">需要管理員完成一次 Google OAuth App 設定，之後使用者只需按「連接 Google」。<a href="/app/admin#google-oauth-setup">前往管理員設定</a></p>`}
   <div class="actions"><button type="button" id="google-connect" ${state.client_configured&&state.key_present?'':'disabled'}>${state.connected?'重新連接 Google':'連接 Google'}</button><button type="button" id="google-recheck" ${state.connected?'':'disabled'}>重新確認免費資格</button><button type="button" id="google-disconnect" ${state.connected?'':'disabled'}>解除此政策的 Google 連接</button></div>
   <div id="google-project-picker" hidden><p>您的 Google 帳號有多個專案，請選擇建立 Gemini Key 的專案；不需輸入 ID。</p><label>Google 專案<select id="google-project-choice"></select></label><button type="button" id="google-project-confirm">確認此專案</button></div>
   <p id="google-operation" role="status"></p><p class="footnote">授權不代表免費資格通過。Google 拒絕、權限不足、撤銷或計費狀態不明時，系統會停止。Google 測試中 App 的長效授權可能在 7 天後到期，屆時需重新連接；MOS 不會繞過限制。</p>`;
  const get=id=>box.querySelector('#google-'+id),op=get('operation');
  const show=s=>{get('connection-status').textContent=s.connected?'Google 已連接；授權憑證已加密保存，由後端維護。'+(s.source==='MOCK'?'（合成 OAuth 測試）':''):s.phase==='STARTED'?'Google 授權尚未完成，請完成官方登入與同意。':reasons[s.error]||({DENIED:'Google 未同意授權；尚不能產文。',EXPIRED:'授權流程已過期，請重新連接。',REVOKED:'Google 連接已解除；Gemini Key 與 Threads 連線保留。',RECONNECT_REQUIRED:'Google 授權已失效，請重新連接。'})[s.phase]||'Google 尚未連接。';};show(state);const marker=new URLSearchParams(location.search).get('google_oauth');if(marker&&marker!=='CONNECTED')op.textContent=reasons[marker]||'Google 授權未完成，請重新連接。';
  const work=async(button,fn)=>action(button,async()=>{try{await fn();}catch(error){op.className='notice error';op.textContent=error.message;show(await api(base+'/google-status'));describe(await api(base+'/gemini-status'));throw error;}});
  const verify=async project=>{op.textContent='正在向 Google 核對專案及免費資格；不會產文。';const result=await api(base+'/google-verify'+(project?'?project_id='+encodeURIComponent(project):''),json({}));describe(result);
   if(result.projects){get('project-picker').hidden=false;get('project-choice').innerHTML='<option value="">請選擇專案</option>'+result.projects.map(p=>`<option value="${esc(p.project_id)}">${esc(p.label)}（${esc(p.project_id)}）</option>`).join('');op.textContent=result.projects.length?'請選擇您的 Gemini 專案。':'Google 未回傳可檢視的專案；請核對登入帳號及專案權限。';}
   else{get('project-picker').hidden=true;op.textContent=result.free_tier_status==='CONFIRMED'?'免費資格已核對；仍未授權產文或發文。':reasons[result.last_error]||'免費資格待確認，產文保持關閉。';}};
  get('connect').onclick=e=>work(e.currentTarget,async()=>{const result=await api(base+'/google-start',json({}));const url=new URL(result.authorization_url);if(url.origin!=='https://accounts.google.com'||url.pathname!=='/o/oauth2/v2/auth')throw Error('Google 授權網址不符，已停止。');location.assign(url.href);});
  get('recheck').onclick=e=>work(e.currentTarget,()=>verify());
  get('project-confirm').onclick=e=>work(e.currentTarget,async()=>{if(!get('project-choice').value)throw Error('請先選擇 Google 專案。');await verify(get('project-choice').value);});
  get('disconnect').onclick=e=>work(e.currentTarget,async()=>{await api(base+'/google-disconnect',json({}));show(await api(base+'/google-status'));describe(await api(base+'/gemini-status'));get('recheck').disabled=true;get('disconnect').disabled=true;op.textContent='此政策在 MOS 的 Google 連接已解除；Gemini Key 與 Threads 保留。若要撤銷 Google 帳號端的 App 授權，請至 Google 帳號權限管理。';});
  if(state.connected){await work(get('recheck'),()=>verify());}
 }

 async function admin(){
  const box=document.createElement('section');box.id='google-oauth-setup';box.className='panel';document.querySelector('#content').append(box);
  let user;try{user=await api('/ui/session');}catch{box.innerHTML='<h2>Google OAuth 首次設定</h2><p>請先登入工作區，再回到此管理員頁面設定 Google App。</p><a href="/app">登入工作區</a>';return;}
  const state=await api('/ui/admin/google-setup?tenant_id='+encodeURIComponent(user.tenant_id));
  box.innerHTML=`<h2>Google OAuth 首次設定（僅管理員）</h2><p>在 <a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noopener noreferrer">Google Auth Platform</a> 建立「網頁應用程式」Client，設定同意畫面及測試使用者，登記下方 Redirect URI。這不是 Gemini API Key；不需要更動 Threads App。</p><p>要求兩項唯讀範圍：cloud-platform.read-only、cloud-billing.readonly。Google App 的發布／驗證與使用者 IAM 權限仍須符合官方要求，MOS 不會自動繞過審查。</p>
   <label>Google OAuth Redirect URI<input id="google-admin-callback" readonly value="${esc(state.callback_uri)}"></label><button type="button" id="google-admin-copy">複製 Callback</button>
   <form id="google-client-form"><label>Google Web Client ID<input name="client_id" value="${esc(state.client_id)}" required autocomplete="off"></label><label>Google Client Secret<input name="client_secret" type="password" required autocomplete="off" minlength="20" maxlength="512"></label><button class="primary">加密保存 Google App 設定</button><p id="google-admin-result" role="status">${state.configured?'已配置；不需重填。僅更換 Google Client 時才重新保存。':'尚未配置，使用者 Google 登入按鈕保持關閉。'}</p></form>`;
  box.querySelector('#google-admin-copy').onclick=e=>action(e.currentTarget,async()=>{await navigator.clipboard.writeText(state.callback_uri);message('Google Callback 已複製。');});
  box.querySelector('form').onsubmit=e=>{e.preventDefault();const f=e.currentTarget;action(e.submitter,async()=>{const result=box.querySelector('#google-admin-result');try{await api('/ui/admin/google-client',json({tenant_id:user.tenant_id,client_id:f.elements.client_id.value.trim(),client_secret:f.elements.client_secret.value}));f.elements.client_secret.value='';result.className='key-saved';result.textContent='Google App 設定已加密保存；不會顯示 Secret。請回到自動化中心按「連接 Google」。';}catch(error){result.className='notice error';result.textContent='未儲存：'+error.message+'。輸入內容仍保留。';throw error;}});};
 }
 return {mount,admin};
})();
