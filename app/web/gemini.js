'use strict';
const GeminiUI=(()=>{
 const model='gemini-3.5-flash-lite';
 const json=body=>({method:'POST',body:JSON.stringify(body)});
 async function mount(host,policy,onSaved){
  const box=document.createElement('section');box.className='panel gemini-connection';host.append(box);
  if(!policy)return;
  if(policy.terms.model!==model){
   box.innerHTML='<h3>改用 Gemini 免費層</h3><p>沿用這份品牌與時段建立 Gemini 草稿；原 OpenAI 政策及 Key 不變。不會生成或發文。</p><button type="button" id="gemini-copy">沿用品牌，建立 Gemini 設定</button>';
   box.querySelector('button').onclick=e=>action(e.currentTarget,async()=>{const p=await api('/automation/policies/'+policy.id+'/gemini-copy',json({}));await onSaved(p.id);});return;
  }
  let testId=null,expiryTimer;const base='/automation/policies/'+policy.id;
  const state=await api(base+'/gemini-status');
  box.innerHTML=`<h3>Google Gemini · ${model}</h3><p class="notice">只允許已核實的免費專案。額度不足就停止，不切換模型。免費層資料可能被 Google 用於改善產品，請只使用已確認可提供的品牌資料。</p>
   <p id="gemini-status" role="status"></p><div class="gemini-key"><p id="gemini-key-state" class="${state.key_present?'key-saved':''}">${state.key_present?'✓ Gemini API Key 已安全保存':'請保存 Gemini API Key（不會覆蓋 OpenAI Key）'}</p>
   <button type="button" id="gemini-key-change" ${state.key_present?'':'hidden'}>更換 Gemini Key</button><div id="gemini-key-entry" ${state.key_present?'hidden':''}><label>Gemini API Key<input id="gemini-key" type="password" autocomplete="off" minlength="20" maxlength="512"></label><button type="button" id="gemini-key-save">安全保存 Gemini Key</button><p id="gemini-key-result" role="status"></p></div></div>
   <p id="gemini-eligibility" class="notice" role="status"></p>
   <section id="google-auth-entry"></section>
   <div class="actions"><button type="button" id="gemini-key-check">測試 Key 連線（不產文）</button><button type="button" id="gemini-generate">確認並測試一次 Gemini 產文</button></div><p id="gemini-operation" role="status"></p><pre id="gemini-result" class="copy-text"></pre>`;
  const field=id=>box.querySelector('#gemini-'+id),op=field('operation');
  const describe=s=>{const eligibility=s.free_tier_status||'PENDING';field('eligibility').textContent=({CONFIRMED:'免費層已確認',PENDING:'待確認：尚不能執行真實產文',NOT_ELIGIBLE:'不符合免費資格：此專案已連結帳單，不能使用本免費模式'})[eligibility]+(s.verification_source==='MOCK'?'（合成測試，非官方實測）':'');field('eligibility').className=eligibility==='CONFIRMED'?'key-saved':eligibility==='NOT_ELIGIBLE'?'notice error':'notice';field('generate').disabled=eligibility!=='CONFIRMED'||!s.generation_enabled;clearTimeout(expiryTimer);if(s.verification_expires_at&&eligibility==='CONFIRMED'){expiryTimer=setTimeout(()=>{field('eligibility').textContent='待確認：免費驗證已過期，請重新檢查。';field('eligibility').className='notice';field('generate').disabled=true;},Math.max(0,Date.parse(s.verification_expires_at)-Date.now()));}if(s.key_present){field('key-state').textContent='✓ Gemini API Key 已安全保存';field('key-state').className='key-saved';}field('status').textContent=`Provider：Google Gemini；模型：${model}；${s.key_present?'Key 已保存':'Key 未配置'}；${s.free_tier_verified?(s.verification_source==='MOCK'?'合成驗證通過（不是官方實測）':'官方唯讀免費資格及模型連線已驗證（有效 10 分鐘）'):s.free_tier_status==='NOT_ELIGIBLE'?'此專案不符合免費模式':'免費資格尚待確認'}；產文測試：${({NOT_RUN:'尚未測試',APPROVED:'等待單次執行',DISPATCHING:'執行中',SETTLED:'已保存測試結果',RECONCILIATION_REQUIRED:'結果待確認，停止重送',REVOKED:'已撤銷'})[s.test_state]||s.test_state}。${s.generation_enabled?'仍需您明確確認一次生成。':'生成開關目前關閉，不會呼叫模型。'}`;if(s.key_connection?.model_access_verified)field('status').textContent+=' Key／模型連線已驗證（'+(s.key_connection.source==='MOCK'?'合成測試':'官方唯讀')+'）。';if(s.last_error)op.textContent=reasons[s.last_error]||s.last_error;if(s.test_result){const r=s.test_result;field('result').textContent=r.receipt?.draft?.draft_text||r.category||r.generation_status||'';}};
  describe(state);
  field('key-check').onclick=e=>run(e.currentTarget,async()=>{const result=await api(base+'/gemini-key-check',json({}));describe(result);const check=result.key_connection;op.textContent=check?.model_access_verified?'Key 與模型連線已驗證；這不代表專案免費資格已確認，也沒有生成文案。':reasons[check?.category]||'Key 連線尚未通過。';});
  const run=async(button,work)=>action(button,async()=>{try{await work();}catch(e){op.className='error';op.textContent=e.message;throw e;}});
  field('key-change').onclick=()=>{field('key-entry').hidden=false;field('key').focus();};
  field('key-save').onclick=e=>run(e.currentTarget,async()=>{const input=field('key');if(input.value.length<20){field('key-result').textContent='Key 長度不足，請貼上完整 Gemini Key。';return;}
   try{await api(base+'/provider-key',json({api_key:input.value,model}));}catch(error){field('key-result').textContent='未儲存：'+error.message+'；輸入內容仍保留。';throw error;}
   input.value='';testId=null;field('key-entry').hidden=true;field('key-change').hidden=false;field('key-state').className='key-saved';field('key-state').textContent='✓ Gemini API Key 已安全保存；請重新檢查免費資格。';describe(await api(base+'/gemini-status'));const auth=box.querySelector('#google-auth-entry');auth.replaceChildren();await GoogleOAuthUI.mount(auth,policy,describe);
  });
  field('generate').onclick=e=>run(e.currentTarget,async()=>{
   const current=await api(base+'/gemini-status');describe(current);
   if(!current.generation_enabled){op.textContent='單次生成開關尚未開啟；本次部署不會自行啟用，請先完成免費資格驗證並另行確認首次測試。';return;}
   if(!current.free_tier_verified){op.textContent='請先連接 Google，完成免費資格確認。';return;}
   if(!confirm('只使用這份品牌需求，執行一次 Gemini 免費層產文（最多 4096 輸入、1024 輸出 Token）；不發布 Threads、不切換付費模型。確認執行？'))return;
   if(!testId){const p=await api(base+'/gemini-test',json({confirm_one_generation_only:true,idempotency_key:crypto.randomUUID()}));testId=p.id;}
   await api('/ai-tests/'+testId+'/execute',json({}));describe(await api(base+'/gemini-status'));op.textContent='單次測試結果已保存；沒有建立公開貼文。結果不明不會自動重送。';
  });
  await GoogleOAuthUI.mount(box.querySelector('#google-auth-entry'),policy,describe);
 }
 return {mount,model};
})();
