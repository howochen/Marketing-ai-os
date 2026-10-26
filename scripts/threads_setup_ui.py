"""Small Windows Tk guide over the existing installer; no new credential transport."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser
from scripts import threads_setup as setup

META='https://developers.facebook.com/apps/'
DOCS='https://developers.facebook.com/docs/threads/get-started/'
ERRORS={
    'INSTALL_DOCKER_AND_NGROK_FIRST':'請先安裝 Docker Desktop 與 ngrok，開啟 Docker Desktop 後按「重新檢查」。',
    'COMMAND_FAILED:docker':'Docker 尚未就緒或建置失敗。請確認 Docker Desktop 正在執行，再重新檢查；資料不會刪除。',
    'HTTPS_CALLBACK_NOT_READY':'HTTPS 或 Callback 尚未連通。請確認網路與 ngrok 帳戶，再重新檢查。',
    'CALLBACK_CHANGED_RECHECK':'ngrok 網址已變更！請重新檢查，將新的完整 Callback 更新到 Meta，再確認保存。',
    'CONFIRM_META_CALLBACK_FIRST':'請先在 Meta 保存畫面上的 Callback，勾選確認後再輸入憑證。',
    'INVALID_THREADS_CREDENTIALS':'App ID須為3–40位數字，Secret格式不正確。請取用 Threads 專用憑證並重新輸入。',
    'BACKEND_CONFIGURATION_NOT_READY':'後端尚未通過完整設定檢查；不會開啟登入。請重新確認 Callback 與憑證。',
    'THREADS_CREDENTIALS_REQUIRED':'請先安全輸入 Threads App ID 與 Secret。',
    'API_TLS_READINESS_FAILED':'本機 HTTPS 後端尚未就緒。請確認 Docker Desktop 與服務健康，再重新檢查。',
    'AGENT_PORT_IN_USE_BY_OTHER_TUNNEL':'本機4041埠已有不同的 ngrok 通道。本工具不會停止它，請管理員核對後再繼續。',
    'DPAPI_FAILED':'Windows 無法解密既有資料，請使用原本的 Windows 帳戶；不要刪除 Vault 或資料卷。',
    'EXISTING_VOLUME_WITHOUT_VAULT':'找到既有資料卷但缺少原加密 Vault，已停止以保護資料。請找回原備份，不可重設憑證。',
}


class Wizard:
    def __init__(self,initialize,release,*,mobile=False):
        self.initialize=initialize;self.release=release;self.mobile=mobile;self.vault=None;self.busy=False
        self.events=queue.Queue();self.closed=False;self.ready=False;self.report=None;self.callback=''
        self.root=tk.Tk();self.root.title('Marketing AI OS — Threads 首次設定')
        self.root.report_callback_exception=lambda kind,value,tb:self.error('UI_OPERATION_FAILED')
        self.root.geometry('820x720');self.root.minsize(720,650)
        ttk.Style(self.root).configure('TLabel',font=('Microsoft JhengHei UI',11))
        ttk.Style(self.root).configure('TButton',font=('Microsoft JhengHei UI',11),padding=7)
        frame=ttk.Frame(self.root,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Threads 首次設定',font=('Microsoft JhengHei UI',20,'bold')).pack(anchor='w')
        ttk.Label(frame,text='先取得 Callback，再設定 Meta，最後輸入憑證。全程不發文、不呼叫 AI。',wraplength=740).pack(anchor='w',pady=(8,12))
        self.stage=tk.StringVar(value='第一階段｜檢查 Docker、ngrok 與 HTTPS')
        ttk.Label(frame,textvariable=self.stage,font=('Microsoft JhengHei UI',13,'bold')).pack(anchor='w',pady=8)
        self.status=tk.StringVar(value='準備檢查。不需要先提供 Threads App ID／Secret。')
        ttk.Label(frame,textvariable=self.status,wraplength=740).pack(anchor='w',pady=6)
        self.body=ttk.Frame(frame);self.body.pack(fill='both',expand=True,pady=10)
        self.retry=ttk.Button(frame,text='重新檢查 Docker／HTTPS／Callback',command=self.prepare);self.retry.pack(anchor='w',pady=6)
        ttk.Label(frame,text='中斷後可再次雙擊 Setup-Threads.cmd；既有資料庫、加密金鑰與憑證會保留。',wraplength=740).pack(anchor='w',pady=6)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.after(80,self.drain);self.auto=self.root.after(200,self.prepare)

    def label(self,text):
        widget=ttk.Label(self.body,text=text,wraplength=740);widget.pack(anchor='w',pady=7);return widget

    def clear(self):
        for widget in self.body.winfo_children():widget.destroy()

    def start(self,work,done):
        if self.busy:return
        self.busy=True;self.retry.configure(state='disabled')
        def background():
            try:self.events.put(('done',done,work()))
            except Exception as exc:self.events.put(('error',self.error, str(exc) if isinstance(exc,setup.SetupError) else type(exc).__name__))
        threading.Thread(target=background,daemon=True).start()

    def drain(self):
        if self.closed:return
        try:
            while True:
                kind,handler,value=self.events.get_nowait()
                if kind!='progress':self.busy=False;self.retry.configure(state='normal')
                handler(value)
        except queue.Empty:pass
        self.root.after(80,self.drain)

    def progress(self,text):self.events.put(('progress',self.status.set,text))

    def error(self,code):
        # Never display raw command output, provider exceptions, payloads or secret values.
        text=ERRORS.get(code,ERRORS.get(code.split(':',1)[0],'設定未完成，請重新檢查；沒有宣稱 OAuth 成功。'))
        if code.startswith('NGROK_START_FAILED:'):text='ngrok 尚未啟動。請確認免費帳戶及 authtoken；可使用下方安全輸入。'
        self.status.set(text)
        if self.vault and not self.ready:
            self.clear();self.label('請處理上方問題，再按「重新檢查」。原有資料與金鑰不會重設。')
            ttk.Button(self.body,text='設定 ngrok authtoken（必要時）',command=self.ngrok_form).pack(anchor='w',pady=8)

    def prepare(self):
        if self.busy:return
        if self.auto:self.root.after_cancel(self.auto);self.auto=None
        self.ready=False;self.clear();self.stage.set('第一階段｜檢查 Docker、ngrok 與 HTTPS')
        self.status.set('正在檢查；不需要 Threads App ID／Secret。')
        def work():
            self.vault=self.initialize()
            return setup.prepare_install(self.vault,self.progress)
        self.start(work,self.callback_page)

    def callback_page(self,result):
        self.clear();self.callback=result['callback'];self.stage.set('第二階段｜將 Callback 保存到 Meta Threads App')
        self.status.set('網址已改變！舊 Callback 不再有效，必須更新 Meta 設定。' if result['changed'] else 'HTTPS 與 Callback 已連通。下一步：複製網址並開啟 Meta 後台。')
        self.label('OAuth Callback URL（請完整複製，包含 /threads/oauth/callback）')
        uri=ttk.Entry(self.body);uri.insert(0,self.callback);uri.configure(state='readonly');uri.pack(fill='x',pady=6)
        row=ttk.Frame(self.body);row.pack(anchor='w',pady=6)
        ttk.Button(row,text='複製 Callback URL',command=self.copy_callback).pack(side='left',padx=(0,10))
        ttk.Button(row,text='開啟 Meta 開發者後台',command=lambda:webbrowser.open(META)).pack(side='left')
        self.label('優先沿用既有 App；確認 App 有「存取 Threads API」使用案例。進入 Threads 的設定，將上方網址加入 Redirect Callback URLs 並保存。不要填到 Facebook Login 的其他 App 設定。')
        self.label('Threads App ID／Secret：在 App 後台找「Threads App ID」及「Threads App secret」（官方欄位位於 App settings → Basic）。使用 Threads 專用值，不是其他 Facebook Login 憑證。')
        ttk.Button(self.body,text='開啟 Meta 官方 Threads 說明',command=lambda:webbrowser.open(DOCS)).pack(anchor='w',pady=4)
        self.confirmed=tk.BooleanVar(value=self.vault.get('meta_redirect_confirmed_for')==self.callback)
        self.confirm=ttk.Checkbutton(self.body,text='我已在這次使用的 Meta Threads App 保存上述完整 Callback',variable=self.confirmed)
        self.confirm.pack(anchor='w',pady=12)
        self.next=ttk.Button(self.body,text='已保存 Callback，繼續輸入 Threads 憑證',command=self.confirm_callback)
        self.next.pack(anchor='w',pady=6)

    def copy_callback(self):
        self.root.clipboard_clear();self.root.clipboard_append(self.callback);self.root.update()
        self.status.set('Callback 已複製。請在 Meta 保存後，勾選確認，再按下方繼續。')

    def confirm_callback(self):
        if self.busy:return
        if not self.confirmed.get():self.status.set('請先到 Meta 保存 Callback，再勾選確認；系統不能代替 Meta 保存。');return
        self.start(lambda:setup.confirm_callback(self.vault,self.callback),lambda _:self.credentials_page())

    def credentials_page(self):
        self.clear();self.stage.set('第三階段｜Windows 本機安全輸入 Threads 憑證')
        self.status.set('Secret 只在此本機隱藏輸入，保存至既有 Windows DPAPI；不傳到網頁或剪貼簿。')
        if self.vault.get('app_id') and self.vault.get('app_secret'):
            self.label('已存在加密保存的 Threads 憑證；重跑不需重新輸入。若改用另一個 App，請先返回並確認該 App 的 Callback。')
            ttk.Button(self.body,text='沿用既有憑證，驗證後端設定',command=self.finish).pack(anchor='w',pady=10)
        self.label('Threads App ID')
        self.app_id=ttk.Entry(self.body);self.app_id.insert(0,self.vault.get('app_id',''));self.app_id.pack(fill='x',pady=6)
        self.label('Threads App Secret（隱藏輸入，不會顯示既有值）')
        self.secret=ttk.Entry(self.body,show='*');self.secret.pack(fill='x',pady=6)
        ttk.Button(self.body,text='安全保存憑證並驗證後端',command=self.save_credentials).pack(anchor='w',pady=12)
        ttk.Button(self.body,text='返回 Callback 設定',command=lambda:self.callback_page({'callback':self.callback,'changed':False})).pack(anchor='w',pady=6)

    def save_credentials(self):
        if self.busy:return
        app_id=self.app_id.get().strip();secret=self.secret.get();self.secret.delete(0,'end')
        try:setup.credentials(self.vault,app_id,secret)
        except Exception as exc:self.status.set(ERRORS.get(str(exc) if isinstance(exc,setup.SetupError) else '', '憑證未保存，請重新檢查本機權限；沒有記錄輸入內容。'));return
        finally:secret=''
        self.finish()

    def finish(self):
        if self.busy:return
        self.clear();self.stage.set('第四階段｜驗證後端設定')
        self.status.set('正在核對 HTTPS、Callback、App 設定及安全開關；通過後才提供登入。')
        self.start(lambda:setup.finish_install(self.vault),self.ready_page)

    def ready_page(self,report):
        self.clear();self.ready=True;self.report=report;self.stage.set('第五階段｜在同一瀏覽器登入 MOS 並連接 Threads')
        self.status.set('後端設定檢查通過；尚未代表 Meta 已授權。下一步：開啟 MOS 登入。')
        self.label('按下方按鈕，複製一次性 MOS 登入碼，在開啟的瀏覽器登入，再按「連接 Threads 帳號」。請在同一瀏覽器完成官方登入與同意，不要切換瀏覽器。')
        ttk.Button(self.body,text='開啟 MOS 登入與 Threads 連接',command=self.open_login).pack(anchor='w',pady=10)
        self.label('完成官方授權並返回 MOS 後，按「驗證官方 Threads 帳號」。沒有真實 ID、必要 scopes 與未到期 expiry 就不會顯示成功。')
        ttk.Button(self.body,text='驗證官方 Threads 帳號',command=self.verify).pack(anchor='w',pady=10)
        self.evidence=tk.StringVar(value='OAUTH_VERIFIED：尚未驗證；發文維持關閉。')
        ttk.Label(self.body,textvariable=self.evidence,wraplength=740).pack(anchor='w',pady=8)

    def open_login(self):
        if self.busy:return
        # Check again immediately before opening a login window; never trust an old UI badge.
        self.start(lambda:setup.diagnose(self.vault),self.login_checked)

    def login_checked(self,report):
        if not report['SETUP_READY'] or report['publishing_enabled']:self.ready=False;self.error('BACKEND_CONFIGURATION_NOT_READY');return
        self.busy=True;self.retry.configure(state='disabled')
        self.root.after(0,self.login)

    def login(self):
        try:setup.login_window(self.vault,mobile=self.mobile,parent=self.root)
        except Exception:self.status.set('MOS 登入視窗尚未開啟，請確認後端連線，再重新操作。')
        finally:self.busy=False;self.retry.configure(state='normal')

    def verify(self):
        self.start(lambda:setup.diagnose(self.vault),self.verified)

    def verified(self,report):
        if report['OAUTH_VERIFIED']:
            accounts=['Threads ID：'+str(c['threads_user_id'])+'\n使用者：'+c['username']+'\nScopes：'+', '.join(c['granted_scopes'])+'\n到期：'+c['token_expires_at'] for c in report['accounts']]
            self.evidence.set('OAUTH_VERIFIED：官方 API 已驗證\n'+'\n'.join(accounts)+'\n不代表已發布貼文。')
        else:self.evidence.set('OAUTH_VERIFIED：尚未完成。請在原瀏覽器完成 Threads 官方授權，再重新驗證；Mock 不列入成功。')

    def ngrok_form(self):
        if self.busy:return
        self.clear();self.label('若 ngrok 尚未配置帳戶，請先在 ngrok 官方後台取得 authtoken，再在本機隱藏輸入。')
        ttk.Button(self.body,text='開啟 ngrok 官方帳戶設定',command=lambda:webbrowser.open('https://dashboard.ngrok.com/get-started/your-authtoken')).pack(anchor='w',pady=5)
        entry=ttk.Entry(self.body,show='*');entry.pack(fill='x',pady=10)
        def save():
            import re
            token=entry.get();entry.delete(0,'end')
            if not re.fullmatch(r'[A-Za-z0-9_-]{10,256}',token):self.status.set('ngrok authtoken格式不正確，沒有保存。');return
            updated={**self.vault,'ngrok_token':token};setup.save(updated);self.vault.update(updated);token=''
            self.prepare()
        ttk.Button(self.body,text='加密保存 ngrok 設定並重新檢查',command=save).pack(anchor='w',pady=8)

    def close(self):
        if self.busy:self.status.set('正在完成本機操作，請等候完成再關閉；不會刪除資料。');return
        self.closed=True;self.release();self.root.destroy()

    def run(self):self.root.mainloop()
