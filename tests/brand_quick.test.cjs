const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const scope={};
vm.runInNewContext(fs.readFileSync('app/web/brand-quick.js','utf8')+';globalThis.quick=BrandQuick;',scope);
const quick=scope.quick;

test('AJ draft contains requested style, topics and conservative limits',()=>{
 const p=quick.suggest('AJ創美學苑','food');
 assert.equal(p.industry,'beauty_scalp');
 assert.equal(p.maxchars,480);
 assert.match(p.tone,/台灣女生生活系幽默/);
 assert.equal(p.topics.split('\n').length,6);
 assert.match(p.source,/待本人確認/);
 assert.match(quick.supplementary(p),/320～450/);
 assert.match(quick.supplementary(p),/不捏造/);
 assert.ok(quick.supplementary(p).length<=800);
 assert.equal(p.knowledge_facts,undefined);
 assert.equal(p.approved_copy,undefined);
});

test('all six industries produce bounded non-AI suggestions',()=>{
 for(const industry of ['beauty_scalp','food','real_estate','ecommerce','education','b2b']){
  const p=quick.suggest('合成品牌',industry);
  assert.equal(p.industry,industry);
  assert.match(p.source,/非 AI/);
  assert.ok(p.description.length<=400&&p.audience.length<=160&&p.tone.length<=80);
  assert.ok(quick.supplementary(p).length<=800);
  assert.ok(p.topics.split('\n').length>0);
 }
});

test('existing tenant Brief wins and is never mutated',()=>{
 const brief={brand:{name:'AJ創美學苑',description:'Owner 原始品牌介紹',forbidden_terms:['原品牌限制']},industry:'beauty_scalp',
  target_audience:'Owner 原始客群',campaign_goal:'Owner 目的',tone:'Owner 語氣',topic:'Owner 題目',
  constraints:{max_chars:420,required_terms:['必要詞'],forbidden_terms:['另一限制']},supplementary:'Owner 原始補充需求'};
 const before=JSON.stringify(brief);const p=quick.suggest(brief.brand.name,brief.industry,brief);
 assert.equal(p.description,brief.brand.description);assert.equal(p.audience,brief.target_audience);
 assert.equal(p.tone,brief.tone);assert.equal(p.maxchars,420);assert.equal(p.topics,'Owner 題目');
 assert.match(p.forbidden,/原品牌限制/);assert.match(p.forbidden,/另一限制/);
 assert.match(quick.supplementary(p),/^Owner 原始補充需求/);
 assert.equal(JSON.stringify(brief),before);
});

test('unknown industry and invalid brand names do not guess',()=>{
 for(const [name,industry] of [['','food'],[' '.repeat(2),'food'],['x'.repeat(61),'food'],['品牌','unknown']]){
  assert.throws(()=>quick.suggest(name,industry));
 }
});

