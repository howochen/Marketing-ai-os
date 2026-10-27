'use strict';
// Suggestions are editable rules, never verified brand facts or model output.
const BrandQuick=(()=>{
 const industries={
  beauty_scalp:['美容保養、頭皮管理、日常洗護','關心美容與頭皮日常照護的台灣女性、上班族',['美容保養日常與迷思','頭皮管理及洗護知識','女生上班生活與保養困擾']],
  food:['餐飲與飲食生活','重視餐飲體驗與日常飲食的在地消費者',['用餐日常與選擇困擾','食材與餐點常見問題','飲食習慣互動討論']],
  real_estate:['租屋與不動產資訊','正在了解租屋或居住選擇的台灣讀者',['看屋準備與常見疑問','居住生活與空間需求','租屋資訊應核對的事項']],
  ecommerce:['商品選購與電商服務','希望了解商品資訊與選購差異的消費者',['日常選購困擾','商品使用前應確認的資訊','購物常見問題']],
  education:['課程與學習服務','正在了解課程與學習方式的學生、家長或成人學習者',['學習生活與常見困擾','選課前應確認的事項','學習習慣互動討論']],
  b2b:['企業專業服務','正在了解專業服務的企業決策者與工作團隊',['團隊工作常見問題','服務諮詢前的準備','專業流程與協作經驗']]
 };
 const labels={description:'品牌介紹',services:'服務領域（待本人確認）',audience:'目標客群',goal:'行銷目標',tone:'品牌語氣',topics:'Threads 內容主題（每行一個）',hook:'建議 Hook 風格',cta:'結尾 CTA 風格',forbidden:'禁用詞（逗號分隔，最多 12 個）',risk:'高風險宣稱與事實限制',length:'建議文章長度',maxchars:'字元硬上限',supplementary:'沿用的補充需求'};
 const targets=['brand','industry','description','audience','goal','tone','topics','forbidden','required','maxchars','supplementary'];
 function suggest(name,industry,existing){
  name=name.trim();
  if(!name||name.length>60||!industries[industry])throw new Error('請先填寫 1～60 字的品牌名稱並選擇產業。');
  const [services,audience,topics]=industries[industry];
  const aj=name==='AJ創美學苑';
  const result={name,industry,services,audience,topics:topics.join('\n'),
   description:`${name}的初始內容方向：分享${services}的日常觀念與常見問題；具體服務仍待本人確認。`,
   goal:'增加 Threads 互動、建立品牌信任，讓有需求的讀者了解品牌',tone:'自然親切、像真人聊天、有生活共鳴，避免制式廣告語氣',
   hook:'用具體生活情境或讀者常見困擾開頭，不使用無根據的驚人結論',cta:'以自然提問邀請分享經驗，不必每篇都導購',
   forbidden:'保證,根治,永久改善,生髮保證,100%',
   risk:'不捏造顧客案例、價格、優惠、服務效果或門市事實。不做無根據的療效、收益或成果保證；專業與高風險資訊不足時交由人工確認。',
   length:'目標 320～450 字元，包含標點與換行；避免重複相同笑點、比喻與模板',maxchars:480,required:'',supplementary:'',source:'內建規則與產業範本（非 AI）'};
  if(aj)Object.assign(result,{industry:'beauty_scalp',services:'美容保養、頭皮管理、頭皮 SPA、日常洗護與保養觀念',
   description:'分享美容保養、頭皮管理與日常洗護知識，以親切自然的方式幫助女性了解保養觀念，並透過生活化內容介紹美容及頭皮 SPA 服務。',
   audience:'台灣女性、上班族、重視美容與頭皮保養的人，以及希望透過保養改善日常照護習慣的族群。',
   goal:'提高 Threads 曝光、增加互動、建立品牌信任、吸引課程諮詢與預約。',
   tone:'台灣女生生活系幽默、像真人聊天、有生活共鳴、偶爾自嘲、輕知識、不像制式衛教文章。',
   topics:['美容保養日常與迷思','頭皮管理及洗護知識','女生上班生活與保養困擾','顧客常見問題','頭皮 SPA 體驗與門市日常（須提供真實資訊）','保養觀念與互動討論'].join('\n'),source:'AJ創美學苑初始範例（待本人確認）'});
  if(existing){
   const b=existing;
   Object.assign(result,{industry:b.industry,description:b.brand.description,audience:b.target_audience,goal:b.campaign_goal,tone:b.tone,
    topics:b.topic,maxchars:b.constraints.max_chars,required:b.constraints.required_terms.join(','),
    forbidden:[...new Set([...b.brand.forbidden_terms,...b.constraints.forbidden_terms])].join(','),supplementary:b.supplementary||'',source:'沿用目前租戶的內容工作台 Brief；新增提示仍待確認'});
  }
  return result;
 }
 function supplementary(p){
  return [p.supplementary,`服務領域（待確認）：${p.services}`,`Hook：${p.hook}`,`CTA：${p.cta}`,`文章長度：${p.length}`,p.risk].filter(Boolean).join('\n');
 }
 function mount(tasks){
  const get=id=>document.querySelector('#auto-'+id);
  const panel=get('brand-suggestions');
  const snapshot=()=>JSON.stringify(targets.map(id=>get(id).value));
  let original,proposal;
  const taskBrief=name=>{
   const selected=tasks.find(t=>t.id===get('brand-template').value)?.brief;
   return selected?.brand.name.trim()===name?selected:tasks.find(t=>t.brief?.brand.name.trim()===name)?.brief;
  };
  function open(preset=false,brief=null){
   try{
    const name=preset?'AJ創美學苑':(brief?.brand.name||get('brand').value.trim());
    proposal=suggest(name,preset?'beauty_scalp':(brief?.industry||get('industry').value),brief||taskBrief(name));
    original=snapshot();
    panel.hidden=false;
    panel.innerHTML=`<h3 tabindex="-1">品牌建議預覽</h3><p class="footnote">來源：${esc(proposal.source)}。這不是已核實的品牌事實，也不會自動加入 Owner 品牌知識或核准素材。</p>
     <p>品牌：<strong>${esc(proposal.name)}</strong>。可逐欄修改；按套用只填入表單，仍須使用原本的儲存按鈕。</p>
     <div class="actions brand-preview-actions"><button type="button" id="brand-apply" class="primary">套用至目前政策</button><button type="button" id="brand-cancel">取消，保留原資料</button></div>
     <label>建議產業<select data-brand-field="industry">${[...get('industry').options].map(o=>`<option value="${esc(o.value)}" ${o.value===proposal.industry?'selected':''}>${esc(o.textContent)}</option>`).join('')}</select></label>
     <div class="form-grid">${Object.entries(labels).map(([key,label])=>`<label>${esc(label)}${key==='maxchars'?`<input data-brand-field="${key}" type="number" min="20" max="500" step="1" value="${esc(proposal[key])}" required>`:`<textarea data-brand-field="${key}" rows="${key==='topics'?6:2}" maxlength="${({description:400,audience:160,goal:160,tone:80,supplementary:800})[key]||800}" ${key!=='supplementary'?'required':''}>${esc(proposal[key])}</textarea>`}</label>`).join('')}</div>
     <p class="footnote">確認後使用上方「套用至目前政策」；套用不是儲存、支出批准或發布授權。</p>`;
    panel.querySelector('h3').focus();
    document.querySelector('#brand-cancel').onclick=()=>{panel.hidden=true;panel.replaceChildren();get('brand-quick').focus();};
    document.querySelector('#brand-apply').onclick=()=>{
     try{
      if(snapshot()!==original)throw new Error('目前政策表單已變更，未套用建議。請重新開啟預覽，避免覆蓋剛才的編輯。');
      for(const field of panel.querySelectorAll('[data-brand-field]')){
       if(!field.reportValidity())return;
       proposal[field.dataset.brandField]=field.value.trim();
       if(field.required&&!proposal[field.dataset.brandField])throw new Error('建議欄位不可只有空白，請填寫後再套用。');
      }
      const words=proposal.forbidden.split(/[,，]/).map(x=>x.trim()).filter(Boolean);
      if(words.length>12||words.some(x=>x.length>60))throw new Error('禁用詞最多 12 個，每個最多 60 字；請調整後再套用。');
      const topics=proposal.topics.split('\n').map(x=>x.trim()).filter(Boolean);
      if(!topics.length||topics.length>60||topics.some(x=>x.length>200))throw new Error('請填寫 1～60 個主題，每個最多 200 字。');
      const extra=supplementary(proposal);
      if(extra.length>800)throw new Error('補充需求與建議規則合計超過 800 字，請精簡後套用；原資料未變更。');
      if(get('brand').value.trim()!==proposal.name&&(get('facts').value.trim()||get('copy').value.trim()))throw new Error('目前草稿已有品牌知識或核准素材。請先核對並移除不屬於新品牌的內容，再重新預覽；不會自動覆寫 Owner 資料。');
      const values={brand:proposal.name,industry:proposal.industry,description:proposal.description,audience:proposal.audience,goal:proposal.goal,tone:proposal.tone,topics:topics.join('\n'),forbidden:words.join(','),required:proposal.required,maxchars:proposal.maxchars,supplementary:extra};
      for(const [id,value] of Object.entries(values))get(id).value=value;
      panel.hidden=true;panel.replaceChildren();get('brand-quick').focus();message('品牌建議已填入目前表單，尚未儲存或授權；已保存的政策不受影響。');
     }catch(e){message(e.message,true);}
    };
    return true;
   }catch(e){message(e.message,true);return false;}
  }
  get('brand-quick').onclick=()=>open();
  get('brand-aj').onclick=()=>open(true);
  get('brand-template').onchange=e=>{const b=tasks.find(t=>t.id===e.target.value)?.brief;if(b)open(false,b);};
  get('brand-ai').onclick=()=>{if(open())message('AI 品牌補全尚未開放：缺少可用品牌補全契約及獨立費用准入。已提供免費規則預覽；沒有呼叫模型。');};
 }
 return {mount,suggest,supplementary};
})();
