"""Visible native Windows UI rehearsal; infrastructure and account access are synthetic."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import threads_setup as setup
from scripts.threads_setup_ui import Wizard
from tkinter import ttk
PRIVATE=ROOT/'.threads-setup-test';setup.PRIVATE=PRIVATE;setup.protect_directory()
vault={'project':setup.PROJECT,'admin':'synthetic-offline-admin','postgres':'preserve-synthetic-database',
    'app':'preserve-synthetic-role','migration':'preserve-synthetic-migration','token_key':'preserve-synthetic-token-key',
    'tenant_id':'synthetic-tenant','public_url':'https://offline-demo.ngrok-free.app',**setup.certificate()}
setup.save(vault)
def prepare(v,progress):
    progress('離線合成環境；沒有執行 Docker、ngrok 或任何外部 API。')
    return {'vault':v,'callback':v['public_url']+'/threads/oauth/callback','changed':False}
setup.prepare_install=prepare
setup.tunnel=lambda v:v['public_url']
setup.finish_install=lambda v:{'SETUP_READY':True,'publishing_enabled':False,'OAUTH_VERIFIED':False,'accounts':[]}
setup.diagnose=lambda v:{'SETUP_READY':True,'publishing_enabled':False,'OAUTH_VERIFIED':False,'accounts':[]}
setup.login_window=lambda *args,**kw:None
import webbrowser
webbrowser.open=lambda url:False
wizard=Wizard(lambda:vault,lambda:None)
wizard.root.title('MOS Threads 安裝器 — 離線 Windows 互動驗收')
ttk.Label(wizard.root,text='離線合成資料驗收｜未執行 Docker／ngrok／真實 OAuth；禁止輸入真正 Secret',foreground='#a6252a').pack(side='bottom',pady=8)
wizard.run()
