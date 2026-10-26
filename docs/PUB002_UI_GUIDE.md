# Threads 帳號管理介面與操作教學

日期：2026-10-26。介面路徑 `/app`；首次設定 `/app/admin`。本次只有合成資料驗收，沒有真實 OAuth、公開貼文或 AI API 支出。

## 本機安全預覽

在專案根目錄 PowerShell 執行：

```powershell
.venv/Scripts/python tests/ui_preview.py
```

開啟 http://127.0.0.1:8787/app 。此專用預覽使用獨立 `.ui-preview/browser.db`，強制 Mock Transport 並禁止真實 Provider HTTP；不是正式工作區。另一個終端取得一次性預覽登入碼：

```powershell
.venv/Scripts/python tests/ui_preview.py --issue-code
(Get-Content .ui-preview/access.json | ConvertFrom-Json).challenge
```

將登入碼貼進「登入工作區」。十分鐘有效、只能使用一次。預覽管理設定所需的是同檔案中的 `admin_secret`（合成值），不是 Meta Secret。不要把此檔案提交或公開。預覽產生的帳號、發文紀錄與權限都不能證明官方驗收完成。Ctrl+C 停止預覽。

## 實際服務啟動（管理員）

重用既有 PostgreSQL 部署，不對客戶資料執行測試或備份演練。先按 `.env.example` 在受控後端配置獨立資料庫角色及 MOS_ADMIN_KEY，然後執行：

```powershell
docker compose up --build -d db migrate api
```

本機入口 http://127.0.0.1:8000/app 。`/health`、`/ready` 用於存活及 migration 檢查。真實帳號使用受信任 HTTPS 反向代理；設定 `MOS_PUBLIC_URL=https://你的網域` 及最小 `MOS_TRUSTED_PROXIES`。不要公開 HTTP 8000；不要信任任意來源的 Forwarded headers。

1. 開啟 `/app/admin`，以後端系統管理員登入密鑰登入。這個權限獨立於 tenant owner。
2. 依精靈官方連結及 [Meta App 設定教學](THREADS_META_APP_SETUP.md) 建立 Threads App、確認測試帳號資格、隱私與資料刪除政策、必要 App Review。後台名稱可能變動，以官方當日介面為準。
3. 將 Threads 專用 ID、Secret、Fernet key 放入受控後端密鑰來源。精靈只顯示是否配置，不能輸入或讀回正式 Secret。
4. 複製精靈產生的 HTTPS Redirect URI 到 Meta 後台，並將完全相同值設為 MOS_THREADS_REDIRECT_URI。URI 固定 `/threads/oauth/callback`。
5. 可點「檢查 HTTPS／Callback」。此為有五秒逾時的伺服器 TLS 探測，不代表 Meta 可達、App Review 或 OAuth 已通過。
6. `MOS_THREADS_HTTP_ENABLED`、`MOS_THREADS_PUBLISH_ENABLED`、`MOS_THREADS_MAINTENANCE_ENABLED` 預設 false。只在持有人準備進行官方登入時由管理員啟用 HTTP；發布開關繼續關閉。模型開關保持 false。
7. 管理者用既有受信任的 `/admin/login-challenges` 配發指定 tenant owner 的短效登入碼（後端管理操作）。一般使用者只收到一次性碼，不接觸 MOS Bearer、Threads Token 或 Swagger。正式身分平台仍是後續 Production Gate。

## 一般使用者

1. 在 `/app` 輸入一次性工作區登入碼，確認工作區名稱。
2. 到「Threads 連接」按「連接 Threads 帳號」。同一瀏覽器跳轉官方登入；核對帳號、用途與要求的權限後才同意。不要把官方登入網址另貼至沒有原始 Cookie 的瀏覽器。
3. 返回頁面核對官方取得的 username、帳號 ID、scopes、到期時間及最後驗證時間。`合成連接` 不是官方授權。若官方權限不足，停止發布並重新授權。
4. 「檢查連線」會重新讀取官方身份；「重新授權」重新跑 OAuth；「更新憑證」只在官方允許的時間使用。「撤銷本地連接」移除本地可用 Token 並停止新發文；Meta 端仍須自行移除 App 授權。
5. 帳號發布許可只是第一道限制，不會自動發文。內容必須經 A21、owner 核准指定 Revision，再到「發布確認與紀錄」。
6. 檢視固定文字、Revision ID、SHA256 及指定帳號；只有本人確定要公開時才勾選並按確認，最後對話框再確認一次。此路徑重用既有 worker 執行及發布防重複；一般頁面載入不發文。
7. 結果不明時不要重按或另建相同貼文。只有官方讀回完成才顯示正式驗證與實際 permalink；仍須本人到 Threads 確認同一篇。Mock 結果不能代替此步。

## 憑證維護與告警

需要管理員配置同 tenant 的有效 worker（含 recover／execute scope），啟動 `docker compose --profile recovery up -d recovery`，並在 API 與 scheduler 同時開啟維護開關。沿用單一 scheduler，不增加服務框架。

七日內到期會顯示提醒；只有長效憑證滿 24 小時且未到期時才刷新。一次失敗即 REAUTH_REQUIRED、禁用發布，頁面顯示原因、Audit 留下失敗事件；不無限自動重試。持久化 IN_PROGRESS 保護中斷後不盲目刷新。告警目前是工作區 UI／審計，沒有新增 Email、SMS 或外部值班服務。

## 故障排查

| 現象 | 處理 |
|---|---|
| 待完成設定 | 請管理員查看精靈列出的 HTTPS、ID、Secret、加密 key、Redirect URI；不要提供 Token 給一般使用者 |
| 登入碼失效 | 取得新的十分鐘一次性碼；不要重複使用 |
| 安全驗證失敗 | 確認同一 HTTPS origin，重新整理；跨網域或清除 Cookie 必須重新登入 |
| OAuth 取消／失敗 | 核對測試角色、App 權限、精確 Redirect URI，再於同一瀏覽器重新授權；錯誤頁不回顯 code |
| 憑證到期／權限撤銷／帳號不一致 | 已停止新發布，重新授權並核對官方帳號與 scopes |
| 尚未滿 24 小時 | 不強迫刷新，等待官方允許時段 |
| Worker 未配置 | 管理員配置同 tenant、同環境且未到期的 worker；owner 不可直接冒用 worker API |
| 結果不明 | 保留既有 Publication，按 THREADS_FAILURE_RECOVERY.md 人工對帳；不可自動重發 |

官方來源查核於 2026-10-26：[Meta Threads 文件](https://developers.facebook.com/docs/threads/)、[Meta 官方 API collection](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)、[官方範例](https://github.com/fbsamples/threads_api)。本次 Meta long-lived 文件無法由研究工具直接讀取；沿用現有保守 24h／未過期限制，真實帳號驗收前須再確認官方規則與 `.com/.net` 端點差異，不能以 Mock 代替。
