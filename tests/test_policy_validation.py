"""Schema remains strict; explicit name confirmation is not service or publication approval."""
import copy
from test_automation import env,setup_policy
from test_threads_publisher import mock_threads


def test_aj_full_brand_guided_can_save_incomplete_draft_but_not_activate(client,env):
    _,owner,_,old,_=setup_policy(client)
    terms=copy.deepcopy(old['terms'])
    terms.update(mode='FULL',creative_mode='BRAND_GUIDED',model='gpt-6-luna',knowledge_facts=[])
    terms['brief']['brand']['name']='AJ創美學苑'
    invalid=client.post('/automation/policies',headers=owner,json={'terms':terms})
    assert invalid.status_code==201
    pending=invalid.json()
    blocked=client.post('/automation/policies/'+pending['id']+'/activate',headers=owner,json={'terms_hash':pending['terms_hash'],'confirm_delegated_publication':True})
    assert blocked.status_code==422
    assert blocked.json()['detail']=='VERIFIED_BRAND_FACTS_REQUIRED_BEFORE_ACTIVATION'
    terms['knowledge_facts']=[{'id':'brand_name','text':'品牌名稱為AJ創美學苑。','source':'Owner在政策表單明確確認品牌名稱'}]
    result=client.post('/automation/policies',headers=owner,json={'terms':terms})
    assert result.status_code==201,result.text
    p=result.json()
    assert p['state']=='DRAFT' and p['terms']['model']=='gpt-6-luna'
    assert p['terms']['knowledge_facts']==terms['knowledge_facts']
    assert p['key_present'] is False
    assert next(x for x in client.get('/automation/policies',headers=owner).json()['policies'] if x['id']==old['id'])['terms']==old['terms']


def test_materials_requirement_and_field_limits_not_relaxed(client,env):
    _,owner,_,old,_=setup_policy(client)
    terms=copy.deepcopy(old['terms']);terms['approved_copy']=[]
    result=client.post('/automation/policies',headers=owner,json={'terms':terms})
    assert result.status_code==201
    pending=result.json()
    blocked=client.post('/automation/policies/'+pending['id']+'/activate',headers=owner,json={'terms_hash':pending['terms_hash'],'confirm_delegated_publication':True})
    assert blocked.status_code==422
    assert blocked.json()['detail']=='THREE_OWNER_APPROVED_COPY_BLOCKS_REQUIRED_BEFORE_ACTIVATION'
    terms['mode']='MANUAL';terms['brief']['brand']['description']='字'*401
    result=client.post('/automation/policies',headers=owner,json={'terms':terms})
    assert result.status_code==422
    assert result.json()['detail'][0]['loc'][-1]=='description'
