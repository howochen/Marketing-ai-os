"""Free brand defaults use the existing Brief and policy HTTP/database path only."""
import json
import shutil
import subprocess
import pytest
from app.content_workbench import Brief
from app.agent_runtime import build_prompt
from app.automation import Terms
from test_automation import env,setup_policy
from test_threads_publisher import mock_threads


def test_brand_rules_in_node():
    if not shutil.which('node'):pytest.skip('Node required for actual frontend rule tests')
    result=subprocess.run(['node','--test','tests/brand_quick.test.cjs','tests/policy_validation.test.cjs'],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stdout+result.stderr


def test_brand_brief_saved_as_new_policy_preserves_old_policy(client,env):
    tid,owner,_,old,_=setup_policy(client)
    import copy
    terms=copy.deepcopy(old['terms'])
    brief=Brief.model_validate(terms['brief'])
    brief.brand.name='AJ創美學苑'
    brief.brand.description='分享美容保養、頭皮管理與日常洗護知識；具體服務待本人確認。'
    brief.tone='台灣女生生活系幽默、像真人聊天、有生活共鳴'
    brief.constraints.max_chars=480
    brief.supplementary='Hook：自然生活情境開頭。CTA：自然提問。目標320～450字元，不捏造服務或療效。'
    terms.update(brief=brief.model_dump(),mode='MANUAL',topics=['美容保養日常與迷思'])
    Terms.model_validate(terms)
    result=client.post('/automation/policies',headers=owner,json={'terms':terms})
    assert result.status_code==201,result.text
    saved=result.json()
    assert saved['state']=='DRAFT' and saved['id']!=old['id']
    assert saved['terms']['brief']['supplementary']==brief.supplementary
    policies=client.get('/automation/policies',headers=owner).json()['policies']
    assert next(p for p in policies if p['id']==old['id'])['terms']==old['terms']
    prompt=build_prompt(brief.request('brand-quick-synthetic'),tid)
    assert brief.tone in prompt and brief.supplementary in prompt
    assert saved['key_present'] is False


def test_incomplete_brand_guided_draft_saves_but_cannot_activate(client,env):
    import copy
    _,owner,_,base,_=setup_policy(client)
    terms=copy.deepcopy(base['terms'])
    terms.update(mode='FULL',creative_mode='BRAND_GUIDED',knowledge_facts=[],approved_copy=[],model='gpt-6-luna')
    response=client.post('/automation/policies',headers=owner,json={'terms':terms})
    assert response.status_code==201,response.text
    saved=response.json()
    assert saved['state']=='DRAFT' and saved['key_present'] is False
    activate=client.post('/automation/policies/'+saved['id']+'/activate',headers=owner,json={
        'terms_hash':saved['terms_hash'],'confirm_delegated_publication':True})
    assert activate.status_code==422
    assert activate.json()['detail']=='VERIFIED_BRAND_FACTS_REQUIRED_BEFORE_ACTIVATION'


def test_incomplete_full_materials_draft_saves_but_cannot_activate(client,env):
    import copy
    _,owner,_,base,_=setup_policy(client)
    terms=copy.deepcopy(base['terms'])
    terms.update(mode='FULL',creative_mode='MATERIALS',approved_copy=[])
    response=client.post('/automation/policies',headers=owner,json={'terms':terms})
    assert response.status_code==201,response.text
    saved=response.json()
    activate=client.post('/automation/policies/'+saved['id']+'/activate',headers=owner,json={
        'terms_hash':saved['terms_hash'],'confirm_delegated_publication':True})
    assert activate.status_code==422
    assert activate.json()['detail']=='THREE_OWNER_APPROVED_COPY_BLOCKS_REQUIRED_BEFORE_ACTIVATION'
