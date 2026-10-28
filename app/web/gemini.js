'use strict';
const GeminiUI=(()=>{
 const model='gemini-3.5-flash-lite';
 const scopes='https://www.googleapis.com/auth/cloud-platform.read-only https://www.googleapis.com/auth/cloud-billing.readonly';
 const googleAuthorize='https://developers.google.com/oauthplayground/#step1&scopes='+encodeURIComponent(scopes);
 const json=body=>({method:'POST',body:JSON.stringify(body)});
 async function mount(host,policy,onSaved){
  const box=document.createElement('section');box.className='panel gemini-connection';host.append(box);
  if(!policy)return;
  if(policy.terms.model!==model){
   box.innerHTML='<h3>改用 Gemini 免費層</h3><p>沿用這份品牌與時段建立 Gemini 草稿；原 OpenAI 政策及 Key 不變。不會生成或發文。</p><button type="button" id="gemini-copy">沿用品牌，建立 Gemini 設定</button>';
   box.querySelector('button').onclick=e=>action(e.currentTarget,async()=>{const p=await api('/automation/policies/'+policy.id+'/gemini-copy',json({}));await onSaved(p.id);});return;
  }
  let token='',testId=null,expiryTimer;const base='/automation/policies/'+policy.id;
  const state=await api(base+'/gemini-status');
  box.innerHTML=`<h3>Google Gemini · ${model}</h3><p class="notice">只允許已核實的免費專案。額度不足就停止，不切換模型。免費層資料可能被 Google 用於改善產品，請只使用已確認可提供的品牌資料。</p>
   <p id="gemini-status" role="status"></p><div class="gemini-key"><p id="gemini-key-state" class="${state.key_present?'key-saved':''}">${state.key_present?'✓ Gemini API Key 已安全保存':'請保存 Gemini API Key（不會覆蓋 OpenAI Key）'}</p>
   <button type="button" id="gemini-key-change" ${state.key_present?'':'hidden'}>更換 Gemini Key</button><div id="gemini-key-entry" ${state.key_present?'hidden':''}><label>Gemini API Key<input id="gemini-key" type="password" autocomplete="off" minlength="20" maxlength="512"></label><button type="button" id="gemini-key-save">安全保存 Gemini Key</button><p id="gemini-key-result" role="status"></p></div></div>
   <p id="gemini-eligibility" class="notice" role="status"></p>
   <section aria-label="確認免費層的步驟"><h4>2. 透過 Google 確認免費資格</h4><p>本站的一鍵 Google 登入尚未接入；目前使用 Google 官方授權工具作為備援。只授權讀取專案與計費資訊，不會開通帳單，也不用手動查找專案 ID 或 Key 資源名稱。</p><ol>
   <li><strong>開啟官方授權工具並登入 Google</strong><p><a id="gemini-google-authorize" href="${esc(googleAuthorize)}" target="_blank" rel="noopener noreferrer">開啟 Google 官方授權（臨時驗證）</a>。已預填兩項唯讀權限，在 Step 1 按「Authorize APIs」，選擇建立 Gemini Key 的 Google 帳號並同意。保持 Google 預設端點，不要勾選「Use your own OAuth credentials」。若出現自訂端點警告，先按「Reset all settings」，再複製下方唯讀權限。</p><p>若 Google 頁面未自動帶入，可按<button type="button" id="gemini-copy-scopes">複製唯讀權限</button>，貼到「Input your own scopes」。</p><details><summary>查看將要求的唯讀權限</summary><p id="gemini-scopes" class="copy-text">${esc(scopes)}</p></details></li>
   <li><strong>取得臨時驗證授權，回到 MOS</strong><p>在官方工具 Step 2 按「Exchange authorization code for tokens」，只複製「Access token」欄位到下方；不是 Refresh token，也不是您的 Gemini Key。請勿分享官方工具網址或勾選將 Token 包含在連結中。</p><label>貼上 Google 臨時驗證權杖（Access token）<input id="gemini-verification-token" type="password" autocomplete="off" maxlength="4096"></label><p class="footnote">此權杖短效且敏感，MOS 只在本頁記憶體與這次後端請求使用，不保存；不要貼聊天或網址。</p><button type="button" id="gemini-projects-load">讀取我的 Google 專案</button></li>
   <li><strong>選擇您在 AI Studio 使用的專案</strong><label>Google 專案<select id="gemini-project-choice"><option value="">先讀取 Google 專案，再從清單選擇</option></select></label><button type="button" id="gemini-discover" disabled>自動找出 Key 並確認免費資格</button><p id="gemini-discovery-result" role="status">系統會在您選定的專案尋找已加密保存的 Key，再向 Google 確認計費狀態；不會產文。</p></li></ol>
   <details><summary>Google 授權工具無法使用？Cloud Shell 備援</summary><p>開啟<a href="https://shell.cloud.google.com/" target="_blank" rel="noopener noreferrer">Google Cloud Shell</a>，登入相同 Google 帳號，依官方畫面同意。複製下方指令到 Cloud Shell 執行，將回傳的短效權杖貼入上方安全欄位。不要開通計費。若手機無法操作這些工具，請專案管理者協助此次驗證，不要繞過 Google 拒絕的授權。</p><code id="gemini-token-command">gcloud auth print-access-token</code><button type="button" id="gemini-copy-command">複製備援指令</button></details></section>
   <details id="gemini-project-details"><summary>進階：自動查找失敗時，由管理員手動設定</summary><p>只有專案未列出、Key 超過查找上限或權限不足時才需要。請先確認 Google 帳號與專案權限，不要為了驗證去開通計費。</p>
   <table><thead><tr><th>名稱</th><th>用途與差異</th></tr></thead><tbody><tr><td>Gemini API Key 字串</td><td>上方密碼欄保存的模型密鑰，會加密；不是以下資源名稱。</td></tr><tr><td>API Key 資源名稱</td><td>projects/數字編號/locations/global/keys/識別碼。用來識別哪把 Key，本身不授予存取權。</td></tr><tr><td>Google OAuth 存取權杖</td><td>由 Google 登入授權後產生，短效且敏感，只讓本次後端進行唯讀查詢；不永久保存。</td></tr></tbody></table>
   <label>Google Cloud Project ID<input id="gemini-project" value="${esc(state.project_id)}" autocomplete="off"></label><label>Google API Key 資源名稱（不是 Key 字串）<input id="gemini-resource" value="${esc(state.key_resource)}" placeholder="projects/專案編號/locations/global/keys/Key識別碼" autocomplete="off"></label><button type="button" id="gemini-project-save">儲存進階專案資料</button><button type="button" id="gemini-check">驗證手動指定的專案</button>
   <p class="footnote">自動查找需 projects.get、keys.list、keys.getKeyString 與計費唯讀權限。手動指定資源可省去 keys.list。權限不足或權杖過期時保持待確認，不能產文。長期排程仍需可持續更新的受控後端唯讀權限。</p><a href="https://docs.cloud.google.com/api-keys/docs/get-info-api-keys" target="_blank" rel="noopener noreferrer">Google 官方：查找 Project 與 Key 資源</a></details>
   <div class="actions"><button type="button" id="gemini-key-check">測試 Key 連線（不產文）</button><button type="button" id="gemini-generate">確認並測試一次 Gemini 產文</button></div><p id="gemini-operation" role="status"></p><pre id="gemini-result" class="copy-text"></pre>`;
  const field=id=>box.querySelector('#gemini-'+id),op=field('operation');
  const describe=s=>{const eligibility=s.free_tier_status||'PENDING';field('eligibility').textContent=({CONFIRMED:'免費層已確認',PENDING:'待確認：尚不能執行真實產文',NOT_ELIGIBLE:'不符合免費資格：此專案已連結帳單，不能使用本免費模式'})[eligibility]+(s.verification_source==='MOCK'?'（合成測試，非官方實測）':'');field('eligibility').className=eligibility==='CONFIRMED'?'key-saved':eligibility==='NOT_ELIGIBLE'?'notice error':'notice';field('projects-load').disabled=!s.key_present;field('generate').disabled=eligibility!=='CONFIRMED'||!s.generation_enabled;clearTimeout(expiryTimer);if(s.verification_expires_at&&eligibility==='CONFIRMED'){expiryTimer=setTimeout(()=>{token='';field('eligibility').textContent='待確認：免費驗證已過期，請重新檢查。';field('eligibility').className='notice';field('generate').disabled=true;},Math.max(0,Date.parse(s.verification_expires_at)-Date.now()));}if(s.key_present){field('key-state').textContent='✓ Gemini API Key 已安全保存';field('key-state').className='key-saved';}field('status').textContent=`Provider：Google Gemini；模型：${model}；${s.key_present?'Key 已保存':'Key 未配置'}；${s.free_tier_verified?(s.verification_source==='MOCK'?'合成驗證通過（不是官方實測）':'官方唯讀免費資格及模型連線已驗證（有效 10 分鐘）'):s.free_tier_status==='NOT_ELIGIBLE'?'此專案不符合免費模式':'免費資格尚待確認'}；產文測試：${({NOT_RUN:'尚未測試',APPROVED:'等待單次執行',DISPATCHING:'執行中',SETTLED:'已保存測試結果',RECONCILIATION_REQUIRED:'結果待確認，停止重送',REVOKED:'已撤銷'})[s.test_state]||s.test_state}。${s.generation_enabled?'仍需您明確確認一次生成。':'生成開關目前關閉，不會呼叫模型。'}`;if(s.key_connection?.model_access_verified)field('status').textContent+=' Key／模型連線已驗證（'+(s.key_connection.source==='MOCK'?'合成測試':'官方唯讀')+'）。';if(s.last_error)op.textContent=reasons[s.last_error]||s.last_error;if(s.test_result){const r=s.test_result;field('result').textContent=r.receipt?.draft?.draft_text||r.category||r.generation_status||'';}};
  describe(state);
  field('key-check').onclick=e=>run(e.currentTarget,async()=>{const result=await api(base+'/gemini-key-check',json({}));describe(result);const check=result.key_connection;op.textContent=check?.model_access_verified?'Key 與模型連線已驗證；這不代表專案免費資格已確認，也沒有生成文案。':reasons[check?.category]||'Key 連線尚未通過。';});
  const run=async(button,work)=>action(button,async()=>{try{await work();}catch(e){op.className='error';op.textContent=e.message;throw e;}});
  field('copy-scopes').onclick=e=>run(e.currentTarget,async()=>{try{await navigator.clipboard.writeText(field('scopes').textContent);op.textContent='兩項唯讀權限已複製；請到 Google 官方授權工具 Step 1 貼上。';}catch{op.textContent='瀏覽器不允許自動複製；請展開「查看將要求的唯讀權限」並長按選取。';}});
  field('copy-command').onclick=e=>run(e.currentTarget,async()=>{try{await navigator.clipboard.writeText(field('token-command').textContent);op.textContent='指令已複製，請到 Google Cloud Shell 貼上執行。';}catch{op.textContent='瀏覽器不允許自動複製，請長按選取上方指令。';}});
  const readToken=()=>{const value=field('verification-token').value.trim()||token;if(!value)throw Error('請先在 Google 官方環境登入，取得短效驗證權杖後貼入安全欄位。');if(value.startsWith('AIza'))throw Error('這看起來是 API Key；請改貼 Google Cloud Shell 這次產生的 OAuth 存取權杖。');return value;};
  field('projects-load').onclick=e=>run(e.currentTarget,async()=>{token=readToken();const result=await api(base+'/gemini-projects',json({verification_access_token:token}));field('verification-token').value='';field('project-choice').innerHTML='<option value="">請選擇 Gemini Key 所在專案</option>'+result.projects.map(p=>`<option value="${esc(p.project_id)}">${esc(p.label)}（${esc(p.project_id)}）</option>`).join('');field('discover').disabled=true;field('discovery-result').textContent=result.projects.length?'請從清單選擇專案，再按自動驗證。'+(result.truncated?'只列出前 100 個專案；未找到時可使用進階設定。':''):'找不到您有權查看的專案。請核對 Google 帳號與 projects.get 權限，這不代表專案已通過免費驗證。';});
  field('project-choice').onchange=()=>{field('discover').disabled=!field('project-choice').value;};
  field('discover').onclick=e=>run(e.currentTarget,async()=>{token=readToken();const result=await api(base+'/gemini-discover',json({verification_access_token:token,project_id:field('project-choice').value}));field('verification-token').value='';field('project').value=result.project_id;field('resource').value=result.key_resource;testId=null;describe(result);field('discovery-result').textContent=result.free_tier_status==='CONFIRMED'?'已自動找出相符 Key 並完成免費資格檢查；沒有產文。':reasons[result.last_error]||'待確認，尚未通過免費資格檢查。';if(!result.free_tier_verified)token='';});
  field('key-change').onclick=()=>{field('key-entry').hidden=false;field('key').focus();};
  field('key-save').onclick=e=>run(e.currentTarget,async()=>{const input=field('key');if(input.value.length<20){field('key-result').textContent='Key 長度不足，請貼上完整 Gemini Key。';return;}
   try{await api(base+'/provider-key',json({api_key:input.value,model}));}catch(error){field('key-result').textContent='未儲存：'+error.message+'；輸入內容仍保留。';throw error;}
   input.value='';token='';field('key-entry').hidden=true;field('key-change').hidden=false;field('key-state').className='key-saved';field('key-state').textContent='✓ Gemini API Key 已安全保存；請重新檢查免費資格。';describe(await api(base+'/gemini-status'));
  });
  field('project-save').onclick=e=>run(e.currentTarget,async()=>{await api(base+'/gemini-project',json({project_id:field('project').value.trim(),key_resource:field('resource').value.trim()}));token='';op.textContent='專案資料已保存；請執行官方唯讀檢查。';describe(await api(base+'/gemini-status'));});
  field('check').onclick=e=>run(e.currentTarget,async()=>{token=field('verification-token').value||token;if(!token){op.textContent='尚缺 Google 官方唯讀驗證權杖；只有 Gemini Key 或免費層勾選不能完成計費驗證。';return;}
   const result=await api(base+'/gemini-check',json({verification_access_token:token}));field('verification-token').value='';describe(result);if(!result.free_tier_verified)token='';else op.textContent='已完成唯讀檢查，尚未產文、未發文。';
  });
  field('generate').onclick=e=>run(e.currentTarget,async()=>{
   const current=await api(base+'/gemini-status');describe(current);
   if(!current.generation_enabled){op.textContent='單次生成開關尚未開啟；本次部署不會自行啟用，請先完成免費資格驗證並另行確認首次測試。';return;}
   if(!current.free_tier_verified||!token){op.textContent='請先完成本頁的免費資格唯讀驗證；過期或重新開頁後需重新檢查。';return;}
   if(!confirm('只使用這份品牌需求，執行一次 Gemini 免費層產文（最多 4096 輸入、1024 輸出 Token）；不發布 Threads、不切換付費模型。確認執行？'))return;
   if(!testId){const p=await api(base+'/gemini-test',json({confirm_one_generation_only:true,idempotency_key:crypto.randomUUID()}));testId=p.id;}
   await api('/ai-tests/'+testId+'/execute',json({verification_access_token:token}));token='';describe(await api(base+'/gemini-status'));op.textContent='單次測試結果已保存；沒有建立公開貼文。結果不明不會自動重送。';
  });
 }
 return {mount,model};
})();
