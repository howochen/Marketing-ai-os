"""Short-lived loopback integration server. Not copied into the runtime image."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
PRIVATE=ROOT/'.phone-setup-test';PRIVATE.mkdir(exist_ok=True)
os.environ['DATABASE_URL']='sqlite:///'+str(PRIVATE/'fixture.db')
os.environ.pop('MIGRATION_DATABASE_URL',None)
os.environ['MOS_PHONE_SETUP_ENABLED']='true';os.environ['MOS_PHONE_SETUP_ALLOW_LOOPBACK']='true'
os.environ['MOS_PUBLIC_URL']='http://127.0.0.1:8891';os.environ['MOS_THREADS_PUBLISH_ENABLED']='false'
from conftest import tenant,ADMIN
from app.main import app
from app.security import admin
from fastapi import Depends
from fastapi.testclient import TestClient
from scripts import phone_setup as native
from scripts import threads_setup as setup
from app import phone_crypto as crypto
setup.PRIVATE=PRIVATE
setup.protect_directory()
vault={'project':setup.PROJECT,'admin':os.environ['MOS_ADMIN_KEY'],'postgres':'synthetic-preserve-database',
       'token_key':'synthetic-preserve-fernet','public_url':os.environ['MOS_PUBLIC_URL']}
os.environ['MOS_PHONE_SETUP_AUTHORITY']=crypto.public(native.authority(vault))
with TestClient(app) as client:
    tid,_,_,_=tenant(client,'Synthetic offline phone setup')
vault['tenant_id']=tid;setup.save(vault)
(PRIVATE/'access.json').write_text(json.dumps({'tenant_id':tid}),encoding='utf-8')


@app.post('/__offline/authorize',dependencies=[Depends(admin)],include_in_schema=False)
def authorize(body: dict):
    with TestClient(app) as client:
        record=client.get('/ui/admin/phone-setup/devices/'+tid+'/'+body['device_id'],headers=ADMIN)
        assert record.status_code==200
        current=setup.load();request=native.prepare(current,record.json(),'123456789')
        response=client.post('/ui/admin/phone-setup/grants',headers=ADMIN,json=request)
        assert response.status_code==200
        return response.json()


@app.post('/__offline/apply/{gid}',dependencies=[Depends(admin)],include_in_schema=False)
def apply(gid: str):
    with TestClient(app) as client:
        response=client.post('/ui/admin/phone-setup/grants/'+gid+'/claim',headers=ADMIN,json={})
        assert response.status_code==200
        applied=native.apply_delivery(response.json());restored=setup.load()
        if restored.get('app_secret')!='synthetic-browser-only-value':raise AssertionError('Decryption mismatch')
        if restored['token_key']!=vault['token_key'] or restored['postgres']!=vault['postgres']:raise AssertionError('Existing key changed')
        assert client.post('/ui/admin/phone-setup/grants/'+gid+'/finish',headers=ADMIN,json={'status':'APPLIED','receipt':applied['receipt']}).status_code==200
        return {'applied':True,'existing_keys_preserved':True,'real_provider_calls':0}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8891,access_log=False)
