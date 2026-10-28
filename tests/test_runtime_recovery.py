import copy
import pytest
from scripts import runtime_recovery as recovery


def test_retry_budget_is_persistent_and_latches():
    state={}
    assert all(recovery.admit(state,'ngrok',i) for i in range(3))
    restarted=copy.deepcopy(state)
    assert not recovery.admit(restarted,'ngrok',4)
    assert not recovery.admit(restarted,'ngrok',7200)
    assert recovery.admit(restarted,'docker',5)


def test_only_exact_original_container_and_closed_flags_can_restart():
    expected={'id':'original','image':'sha256:pinned','volumes':['existing-data']}
    item={'Id':'original','Image':'sha256:pinned','Mounts':[{'Type':'volume','Name':'existing-data'}],
          'Config':{'Env':['MOS_MODEL_CALLS_ENABLED=false']}}
    recovery.validate(item,expected)
    for field,value in [('Id','replacement'),('Image','new-image')]:
        changed=copy.deepcopy(item);changed[field]=value
        with pytest.raises(RuntimeError):recovery.validate(changed,expected)
    item['Config']['Env']=['MOS_MODEL_CALLS_ENABLED=true']
    with pytest.raises(RuntimeError,match='LIVE_SWITCH_NOT_CLOSED'):recovery.validate(item,expected)


def test_database_volume_must_not_change():
    item={'Id':'original','Image':'pinned','Mounts':[{'Type':'volume','Name':'wrong'}],'Config':{'Env':[]}}
    with pytest.raises(RuntimeError,match='DATABASE_VOLUME_CHANGED'):
        recovery.validate(item,{'id':'original','image':'pinned','volumes':['existing-data']})


def test_ngrok_restart_pins_url_and_never_logs_secret(tmp_path,monkeypatch):
    monkeypatch.setattr(recovery,'PRIVATE',tmp_path)
    monkeypatch.setattr(recovery,'tunnel',lambda:'https://assigned.ngrok-free.dev')
    monkeypatch.setattr(recovery.setup,'agent_process',lambda _:123)
    monkeypatch.setattr(recovery.shutil,'which',lambda _:'ngrok.exe')
    calls=[]
    class Process:
        pid=42
        def __init__(self,args,**kwargs):calls.extend(args)
        def poll(self):return None
    monkeypatch.setattr(recovery.subprocess,'Popen',Process)
    state={};recovery.start_tunnel({'ngrok_token':'synthetic-secret'},state,'https://assigned.ngrok-free.dev')
    assert '--url=https://assigned.ngrok-free.dev' in calls
    assert 'synthetic-secret' not in str(calls)
    assert not (tmp_path/'ngrok-runtime.yml').exists()
    assert state['ngrok_pid']==42
