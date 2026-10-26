"""Local-only manual workspace. Uses existing passwordless login, never the Threads vault."""
import json
import os
from pathlib import Path
import secrets
import socket
import webbrowser


def main():
    root=Path(__file__).resolve().parents[1]
    os.chdir(root)
    # A second launch must not mint a login for a server it does not own.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',8893))==0:
            print('本機8893埠已使用，請返回原工作台視窗。');return
    private=root/'.content-local';private.mkdir(exist_ok=True)
    if private.is_symlink() or private.is_junction():raise RuntimeError('LOCAL_DIRECTORY_MUST_NOT_BE_LINK')
    os.environ['DATABASE_URL']='sqlite:///'+str(private/'content.db')
    os.environ.pop('MIGRATION_DATABASE_URL',None)
    os.environ.update(MOS_ENV='development',MOS_PUBLIC_URL='http://127.0.0.1:8893',MOS_TRUSTED_PROXIES='',MOS_ADMIN_KEY=secrets.token_urlsafe(48))
    for key in ('MOS_PHONE_SETUP_ENABLED','MOS_MODEL_CALLS_ENABLED','MOS_LIVE_TESTS','MOS_THREADS_HTTP_ENABLED','MOS_THREADS_PUBLISH_ENABLED','MOS_THREADS_MAINTENANCE_ENABLED'):
        os.environ[key]='false'
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config('alembic.ini'),'head')
    from app.database import SessionLocal,scope
    from app.models import Tenant,LoginChallenge,now
    from app.security import uid,audit,digest
    from datetime import timedelta
    state=private/'workspace.json'
    with SessionLocal() as s:
        if state.exists():
            tid=json.loads(state.read_text(encoding='utf-8'))['tenant_id'];scope(s,tid)
            if not s.get(Tenant,tid):raise RuntimeError('WORKSPACE_MISSING_DO_NOT_RESET')
        else:
            tid=uid();scope(s,tid);s.add(Tenant(id=tid,name='本機內容工作區',budget_micro=0));s.commit()
            state.write_text(json.dumps({'tenant_id':tid}),encoding='utf-8')
        code=secrets.token_urlsafe(36)
        s.add(LoginChallenge(id=uid(),tenant_id=tid,subject='local-workspace-owner',token_hash=digest(code),expires_at=now()+timedelta(minutes=10)))
        audit(s,tid,'login.challenge_issued',tid);s.commit()
    print('內容工作台：http://127.0.0.1:8893/app/content')
    print('一次性登入碼（十分鐘有效，只在本機視窗顯示，請勿轉傳）：\n'+code)
    print('資料保存在 .content-local；關閉此視窗停止服務。無公開通道、AI或發文功能。')
    webbrowser.open('http://127.0.0.1:8893/app/content')
    import uvicorn
    uvicorn.run('app.main:app',host='127.0.0.1',port=8893,access_log=False,log_level='warning')


if __name__=='__main__':main()
