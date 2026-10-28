const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');
const context={};vm.runInNewContext(fs.readFileSync('app/web/automation.js','utf8')+';globalThis.validation=AutomationCenter;',context);
const {validateTerms,serverErrors}=context.validation;
const terms=()=>({mode:'FULL',creative_mode:'BRAND_GUIDED',connection_id:'test-account',brief:{brand:{name:'AJ創美學苑',description:'Owner提供的品牌初始建議，服務與療效仍待確認。'},target_audience:'台灣女性',campaign_goal:'增加互動',tone:'台灣女生生活系幽默',topic:'頭皮日常',supplementary:'',constraints:{max_chars:480,required_terms:[],forbidden_terms:[]}},topics:['頭皮日常'],approved_copy:[],knowledge_facts:[],sensitive_terms:[],times:['09:00'],weekdays:[0,1,2],daily_max:1,monthly_budget_micro:10000,starts_at:'2026-10-28T00:00:00Z',expires_at:'2026-10-29T00:00:00Z'});
const clock=Date.parse('2026-10-28T01:00:00Z');
test('brand suggestions cannot satisfy Owner facts automatically',()=>{
 const t=terms(),before=JSON.stringify(t);const errors=validateTerms(t,clock);
 assert.equal(errors.length,0);assert.ok(validateTerms(t,clock,true).some(x=>x.id==='facts'));assert.equal(JSON.stringify(t),before);
 t.knowledge_facts=[{id:'brand_name',text:'品牌名稱為AJ創美學苑。',source:'Owner明確確認品牌名稱'}];
 assert.equal(validateTerms(t,clock).length,0);
 t.knowledge_facts.push({...t.knowledge_facts[0]});assert.ok(validateTerms(t,clock).some(x=>x.id==='facts'));
});
test('full materials requires three real approved blocks',()=>{
 const t=terms();t.creative_mode='MATERIALS';assert.equal(validateTerms(t,clock).length,0);assert.ok(validateTerms(t,clock,true).some(x=>x.id==='copy'));
 t.approved_copy=['Owner完整段落一','Owner完整段落二','Owner完整段落三'];assert.equal(validateTerms(t,clock).length,0);
});
test('manual draft retains data without inventing facts',()=>{
 const t=terms();t.mode='MANUAL';t.creative_mode='MATERIALS';assert.equal(validateTerms(t,clock).length,0);assert.equal(t.knowledge_facts.length,0);
});
test('length, input, budget, schedule and expiry point to exact fields',()=>{
 const t=terms();t.mode='MANUAL';t.creative_mode='MATERIALS';t.brief.brand.description='字'.repeat(401);t.brief.tone='字'.repeat(81);t.topics=['字'.repeat(201)];t.weekdays=[0,0];t.times=['25:00'];t.monthly_budget_micro=0;t.expires_at=t.starts_at;
 const ids=validateTerms(t,clock).map(x=>x.id);for(const id of ['description','tone','topics','days','times','budget','expires'])assert.ok(ids.includes(id));
});
test('real backend 422 root and nested errors translate without echoing input',()=>{
 const root=serverErrors([{loc:['body','terms'],type:'value_error',msg:'Value error, Unique owner facts required',input:{secret:'never-output'}}]);assert.equal(root[0].id,'facts');assert.ok(!JSON.stringify(root).includes('never-output'));
 const nested=serverErrors([{loc:['body','terms','brief','brand','description'],type:'string_too_long',input:'never-output'}]);assert.equal(nested[0].id,'description');assert.match(nested[0].message,/品牌介紹/);assert.ok(!JSON.stringify(nested).includes('never-output'));
 assert.equal(serverErrors('POLICY_ALREADY_EXPIRED')[0].id,'expires');
});
