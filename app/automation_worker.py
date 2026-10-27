"""One restartable tenant worker; use only the credentials minted by Owner policy activation."""
import os
import signal
import threading
from sqlalchemy import select
from .database import SessionLocal,scope
from .models import AutomationPolicy,Credential
from .security import digest
from .threads_api import ThreadsAPI,unseal
from .automation import tick
from .operations import emit


def run_once() -> int:
    tid=os.getenv('MOS_AUTOMATION_TENANT_ID','')
    if not tid or os.getenv('MOS_AUTOMATION_ENABLED','false')!='true':raise ValueError('Explicit tenant and automation activation required')
    count=0
    with SessionLocal() as s:
        scope(s,tid)
        ids=list(s.scalars(select(AutomationPolicy.id).where(AutomationPolicy.tenant_id==tid,AutomationPolicy.state=='ACTIVE')))
        for pid in ids:
            scope(s,tid);p=s.get(AutomationPolicy,pid,populate_existing=True)
            if not p or not p.worker_ciphertext:continue
            try:
                token=unseal(p.worker_ciphertext,tid,'automation-worker:'+p.id)
                scope(s,token_hash=digest(token))
                c=s.scalar(select(Credential).where(Credential.token_hash==digest(token)))
                scope(s,tid)
                if not c or c.tenant_id!=tid:continue
                tick(c,s,ThreadsAPI());count+=1
            except Exception:
                s.rollback();emit('scheduler.failed')
    return count


def main() -> None:
    if os.getenv('MOS_AUTOMATION_ENABLED','false')!='true':raise RuntimeError('Automation worker disabled')
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    while not stop.is_set():
        try:emit('scheduler.completed',count=run_once())
        except Exception:emit('scheduler.failed')
        stop.wait(30)


if __name__=='__main__':main()
