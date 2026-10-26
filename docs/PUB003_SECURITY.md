# PUB003 安全與選型

沿用 Python／cryptography／HTTPX、FastAPI、SQLAlchemy、PostgreSQL、現有 Threads Adapter、OAuth、加密 Token、Tenant RLS、QA、Revision 與發布防重複。新增的只是 Windows CLI 安裝器、啟動器及受控 TLS entrypoint；無新 Python/npm 套件、前端框架或常駐平台。

- 專用 `mos-threads-local` project，連線工作區與測試 project 分開。固定 loopback 18080，不修改原 Compose 預設端口或客戶 volume。沒有 vault 卻存在 volume 時拒絕接管。
- 使用 Windows CSPRNG、current-user DPAPI，私有目錄精確 protected DACL 僅當前使用者／SYSTEM FullControl。重跑不輪替 DB 密碼或 Fernet key；本機管理員仍能檢視執行中程序／Docker 配置，不能把此方案當硬體密鑰庫。
- 正式 Meta Secret 只由互動終端隱藏輸入；非 TTY 拒絕秘密輸入。持久化 vault 為 DPAPI 密文，不寫入 `.env`、Git、log 或一般帳號 API。Compose 明文 env 僅在受保護目錄短暫產生、finally 刪除；程序異常退出可能殘留，下一次在套用 DACL 後清除。Windows pagefile／備份／記憶體不在應用程式可保證清除範圍。
- Docker 執行中的環境仍含所需後端 Secret，這是受控後端配置，不是一般使用者可讀的 Secret Store API。TLS 私鑰只在容器暫存目錄 0600 物化；退出清除。DPAPI 檔與私有目錄都被 gitignore/dockerignore 排除。
- ngrok 預設 HTTP inspection 及 agent log 關閉；新 token 只透過暫存配置傳入，沒有命令列 token；沿用既有 ngrok 設定時不改寫原檔。程序停止同時核對 PID、執行檔及建立時間，避免誤殺其他程序。
- ngrok upstream 使用安裝器生成的 localhost IP 憑證與明確 CA 驗證；API 本身為 TLS，不信任 Forwarded headers，trusted proxies 為空，不使用 wildcard CIDR。
- 真實公開檢查使用 HTTPX 嚴格憑證驗證、無環境代理／redirect；管理員憑證僅送本機固定 TLS API。公開測試只 GET readiness、UI、空 callback，無官方登入 code、Token 或後端 secret。
- 官方身份診斷重用原本 owner `/check`；臨時 owner credential 用後撤銷，Mock 完全排除。官方錯誤會走既有 REAUTH_REQUIRED 並停用發布。安裝器不呼叫 publish 或模型 API；發布／模型旗標即使由 host 設為 true 也不會傳入。
- CLI 禁止 CI/pytest 環境執行真實安裝；CI 只跑 Mock／單元測試。另有 Windows job 驗證原生 DPAPI，Linux 明確跳過其專屬案例。

剩餘限制：ngrok 是第三方 TLS 終止與流量處理者，關閉本機 inspection 不等於能保證第三方零保留；只適用受控開發，勿放正式客戶資料。沒有查得使用者 ngrok 帳戶帳務方案，因此不宣稱帳單驗真；本次沒有購買或升級。沒有可驗證的 Meta App 管理 API；後台、MFA、審查及本人同意均需交接。DPAPI 依賴原 Windows 身分與其備份，遺失 key 不可用新 key 覆寫舊資料來「修好」。第一次工作區建立與 vault 存檔跨 HTTP／檔案，並非分散式原子交易；若在該瞬間中斷，需核對可能的空白工作區。
