'use strict';
// Reorganize the existing form and Key endpoint; never persist secrets in browser storage.
const AutomationWizard=(()=>{
 function mount(data,accounts,selectedId,onSaved){
  const form=document.querySelector('#auto-form');if(!form)return;
  const create=document.querySelector('#auto-create');
  const nav=document.createElement('nav');nav.className='setup-steps';nav.setAttribute('aria-label','首次設定步驟');
  nav.innerHTML=['品牌設定','連接 AI','自動發文設定'].map((x,i)=>`<button type="button" data-setup-step="${i}">${i+1}. ${x}</button>`).join('');
  create.prepend(nav);
  const panels=['品牌設定','連接 AI','自動發文設定'].map((name,i)=>{
   const panel=document.createElement('section');panel.id='setup-step-'+i;panel.className='setup-step';panel.setAttribute('aria-label',name);form.append(panel);return panel;
  });
  const move=(ids,panel)=>ids.forEach(id=>{const e=document.querySelector('#auto-'+id);if(e)panel.append(e.closest('label')||e);});
  panels[0].append(document.querySelector('.brand-start'));
  const applied=document.createElement('p');applied.id='brand-applied-status';applied.setAttribute('role','status');panels[0].append(applied);
  form.addEventListener('input',()=>{applied.textContent='品牌資料如有修改，請確認後儲存設定。';applied.className='muted';});
  // The listener belongs to this render, avoiding stale detached elements after saving.
  document.onmosBrandApplied=()=>{applied.textContent='✓ 品牌建議已套用，可編輯；儲存設定後才會保存。';applied.className='key-saved';};
  move(['brand-template','description','audience','goal','tone','topics','maxchars','required','forbidden','supplementary'],panels[0]);
  move(['model'],panels[1]);
  const provider=document.createElement('label');provider.textContent='AI Provider';const providerSelect=document.createElement('select');providerSelect.id='auto-provider';providerSelect.innerHTML='<option value=mock>離線模擬</option><option value=openai>OpenAI</option><option value=gemini>Google Gemini 免費層</option>';provider.append(providerSelect);panels[1].prepend(provider);
  providerSelect.onchange=()=>{document.querySelector('#auto-model').value=providerSelect.value==='gemini'?GeminiUI.model:providerSelect.value==='openai'?'gpt-6-luna':'mock-a09-v1';if(providerSelect.value==='gemini')document.querySelector('#auto-maxchars').value=Math.min(480,Number(document.querySelector('#auto-maxchars').value)||480);refresh();};
  const connect=document.createElement('div');connect.id='setup-ai-connection';panels[1].append(connect);
  const policies=data.policies.filter(p=>p.state!=='REVOKED');
  const choose=document.createElement('select');choose.id='setup-ai-policy';choose.setAttribute('aria-label','選擇要連接 AI 的已儲存設定');
  choose.innerHTML='<option value="">新的設定（尚未儲存）</option>'+policies.map(p=>`<option value="${esc(p.id)}">${esc(p.terms.brief.brand.name)} · ${esc(p.terms.model)}${p.key_present?' · Key 已保存':''}</option>`).join('');
  const returned=new URLSearchParams(location.search).get('policy');if(!selectedId&&policies.some(p=>p.id===returned))selectedId=returned;
  choose.value=selectedId||policies.find(p=>p.key_present)?.id||'';connect.append(choose);
  const info=document.createElement('div');info.setAttribute('aria-live','polite');connect.append(info);
  const summary=document.createElement('section');summary.className='panel setup-overview';summary.setAttribute('aria-label','設定狀態總覽');create.before(summary);
  const policiesHeading=document.querySelector('.section-heading');policiesHeading.before(summary,create);
  const keyForms=[...document.querySelectorAll('[data-auto-key]')];
  keyForms.forEach(f=>{connect.append(f);f.hidden=true;f.addEventListener('submit',e=>e.stopPropagation());});
  let generation=0;const refresh=()=>{
   const p=policies.find(x=>x.id===choose.value);
   const old=connect.querySelector('.gemini-connection');if(old)old.remove();const index=++generation;
   if(p&&(p.terms.model===GeminiUI.model||document.querySelector('#auto-model').value===GeminiUI.model)){GeminiUI.mount(connect,p,onSaved).catch(error=>{if(index===generation)message(error.message,true);});}
   keyForms.forEach(f=>{f.hidden=f.dataset.autoKey!==p?.id;});
   info.innerHTML=p?(p.key_present?'<p class="key-saved" role="status">✓ API Key 已安全保存，不需要重複輸入。</p><p>這只確認安全保存；模型權限與付費測試須另行驗證。</p>':p.terms.model==='mock-a09-v1'&&p.terms.semantic_reviewer!=='MODEL_REQUIRED'?'<p>此設定使用離線模擬，不需要 API Key。要使用 OpenAI，請在新設定選擇 OpenAI 模型後儲存。</p>':'<p>請在下方安全輸入 Key。儲存 Key 不會呼叫模型或啟用發文。</p>'):'<p>API Key 必須綁定已儲存的設定。請先確認第 3 步的時間、預算與期限，按「儲存設定」，系統會回到這裡讓您保存 Key。</p><button type="button" id="setup-save-first">前往發文設定並儲存</button>';
   const next=document.querySelector('#setup-save-first');if(next)next.onclick=()=>show(2);
   const connection=accounts.find(c=>c.id===p?.terms.connection_id);
   const connected=p?connection?.connection_status==='ACTIVE':accounts.some(c=>c.connection_status==='ACTIVE');
   const aiTest=p&&(data.ai_smoke_tests||[]).some(t=>t.id===p.terms.live_ai_test_id);
   summary.innerHTML='<h2>設定狀態總覽</h2>'+`<p>Threads：${connected?'已連接':'尚未連接'} · 品牌：${p?'已儲存 '+esc(p.terms.brief.brand.name):'尚待儲存'}</p><p>AI Key：${p?.key_present?'✓ 已安全保存':'尚未保存／離線不需要'} · AI 測試：${aiTest?'已有真實測試紀錄':'尚未完成真實測試'}</p><p>自動發文：${data.enabled&&data.live_execution_enabled&&p?.state==='ACTIVE'&&p.terms.execution_mode==='LIVE'?'已取得排程准入，仍受發布安全開關限制':'未啟用'}</p><p class="footnote">${p?'目前查看已儲存設定；下方表單建立的是新版本，不會自動修改這份設定。':'表單內容尚未儲存。'}保存 Key 不等於已連接模型；儲存設定不代表同意支出或公開發布。</p>`;
  };
  const syncProvider=()=>{const p=policies.find(x=>x.id===choose.value);if(p)providerSelect.value=p.terms.model===GeminiUI.model?'gemini':p.terms.model==='gpt-6-luna'?'openai':'mock';};choose.onchange=()=>{syncProvider();refresh();};syncProvider();
  move(['account','mode','daily','times','days','budget','starts','expires','creative-mode','facts','copy'],panels[2]);
  const advanced=document.createElement('details');advanced.innerHTML='<summary>進階：審查、測試與執行限制</summary>';panels[2].append(advanced);
  move(['execution','ai-smoke','publish-smoke','semantic','rewrites','sensitive','mode-help'],advanced);
  form.querySelectorAll(':scope > p').forEach(p=>advanced.append(p));
  const rename=(id,text)=>{const field=document.querySelector('#auto-'+id);if(field?.closest('label')?.firstChild?.nodeType===Node.TEXT_NODE)field.closest('label').firstChild.textContent=text;};
  rename('ai-smoke','單次真實 AI 測試紀錄');rename('publish-smoke','本人帳號測試貼文紀錄');
  rename('facts','本人確認的品牌事實（每行：識別碼|事實|來源）');rename('copy','本人核准的文案素材（每行一段，含開頭與結尾互動）');
  rename('model','新設定使用的模型（既有設定請從下方選擇）');
  document.querySelector('#auto-execution option[value=LIVE]').textContent='真實排程（需測試及獨立授權）';
  const help=document.createElement('p');help.className='notice';help.textContent='儲存只建立未啟用的設定。真實 AI 測試、測試貼文與持續自動發文各需另外確認；本步驟不會啟用任何服務。';panels[2].prepend(help);
  const save=form.querySelector(':scope > button.primary');save.textContent='儲存設定（不啟用發文）';panels[2].append(save);
  const show=index=>{panels.forEach((p,i)=>p.hidden=i!==index);nav.querySelectorAll('button').forEach((b,i)=>{b.setAttribute('aria-current',i===index?'step':'false');});create.open=true;};
  nav.querySelectorAll('button').forEach((b,i)=>b.onclick=()=>show(i));
  panels.forEach((p,i)=>{const footer=document.createElement('div');footer.className='actions setup-navigation';for(const [text,step] of [[i?'上一步':null,i-1],[i<2?'下一步':null,i+1]])if(text){const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=()=>show(step);footer.append(b);}p.append(footer);});
  // Error links must reveal their step before focusing a hidden field.
  form.addEventListener('click',e=>{const b=e.target.closest('[data-policy-error]');if(!b)return;const field=document.querySelector('#auto-'+b.dataset.policyError);const index=panels.findIndex(p=>p.contains(field));if(index>=0){show(index);const details=field.closest('details');if(details)details.open=true;field.focus();}});
  refresh();show(selectedId?1:0);
 }
 document.addEventListener('mos-brand-applied',()=>document.onmosBrandApplied?.());
 return {mount};
})();
