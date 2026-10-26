# Threads 真實連線準備：Windows 首次安裝

2026-10-26。這是受控開發／本人帳號驗收環境，**不是 Production**。安裝器不呼叫 AI、不發布、不修改既有部署或資料卷。

## 使用者操作

1. 打開 Docker Desktop，確認引擎啟動。本機已確認 Python 3.12、Docker 29.5.3／Compose 5.1.4、ngrok 3.22.0 可用。全新電腦需先從官方安裝 Python 3.12、Docker Desktop 和 ngrok；需要免費 ngrok 帳號與有效 authtoken。精靈不購買、升級或代辦帳號。
2. 在專案根目錄雙擊 **Setup-Threads.cmd**，或在 PowerShell 執行：

   ```powershell
   cd D:\AI\Marketing-ai-os
   .\Setup-Threads.cmd
   ```

   若尚無 `.venv`，啟動器建立 venv 並安裝既有鎖定的 requirements.txt。既有 venv 直接重用；不新增框架。
3. 輸入 Threads 專用 App ID。App Secret 使用隱藏輸入，僅存 Windows 當前使用者 DPAPI 加密資料；**不要貼到聊天、Git 或一般 UI API**。尚未建立 Meta App 可 Enter 略過，先取得 Redirect URI，完成後重跑即可。ngrok 已配置則沿用；需要新 authtoken 時可在同一精靈隱藏輸入並加密儲存。
4. 精靈自動產生獨立資料庫密碼、後端金鑰、Fernet key、TLS 憑證，啟動專用 Docker project `mos-threads-local`，取得 ngrok HTTPS。完整 Redirect URI 自動配置到後端並顯示，不用編輯環境變數、Compose 或 Callback 字串。
5. 依下節完成 Meta 後台。若精靈詢問「已保存這個 URI？」只有真正保存後才回答 y。這是使用者聲明，**不是官方驗證**；URL 變動時舊聲明失效。
6. 啟動器現在預設手機交接：顯示 iPhone 可開啟的 `/app/threads` 網址與十分鐘一次性工作區登入碼，不開 Windows Chrome。登入碼不寫到檔案或終端輸出；一般使用者不需要 Swagger、Bearer 或手動交換 Threads Token。詳見 [手機首次初始化](THREADS_MOBILE_FIRST.md)。
7. 到「Threads 連接」點官方 OAuth 按鈕；本人在官方頁面登入、核對帳號及同意授權。ngrok 免費網址可能先顯示 Visit Site 提示；持有人確認網域後繼續，這不等於 Threads 同意。
8. 回到 UI 核對真實官方帳號 ID、username、權限、到期時間。再執行：

   ```powershell
   .\Setup-Threads.cmd --diagnose
   ```

   診斷會重用既有 `/check` 向官方重新驗證已連接帳號；只有 OFFICIAL_API、有效權限、未過期且新驗證成功才 OAUTH_VERIFIED。Mock 不計入。沒有帳號時不會假裝查到 ID。

重新開啟登入視窗：` .\Setup-Threads.cmd --login `。停止專用服務與本安裝器建立的 ngrok：` .\Setup-Threads.cmd --stop `。資料卷、加密 key 保留，重跑會重用。不要刪除 `.threads-local/vault.dpapi` 來「重設」：它包含舊資料解密所需金鑰，且只可由同一 Windows 使用者解密；需連同 Windows 憑證保護規劃離線備份與復原。

## Meta 後台交接（必要人工步驟）

目前未找到可用且經官方文件確認、能代寫 Threads App Redirect URI／完成 App Review 的管理 API。本工具**沒有完成這些後台操作**。瀏覽器操作清單亦提供於 [meta-handoff.json](pub003/meta-handoff.json)；它是具明確停點的自動化操作規格，未假造已觀察到的 DOM selector。

1. 開啟 [Meta 我的應用程式](https://developers.facebook.com/apps/)。本人完成登入、MFA／身分檢查；自動化必須在此暫停，不能讀取 Cookie 或代答安全驗證。
2. 建立／選擇提供 Threads API 的 App，依當日後台找到 Threads use case 設定。確認是 **Threads 專用** ID／Secret，不是一般 Facebook App 憑證。
3. 將精靈顯示的完整 `https://…/threads/oauth/callback` 貼入 Redirect Callback URLs，儲存後重新打開核對。這是 OAuth Redirect，不是 Webhook Verify Callback。不要自行補斜線或 query。
4. 依後台要求配置隱私政策、資料刪除方式、測試帳號／角色及必要審查。本人接受角色邀請；不能以 Mock 錄影、假政策或繞過審查取代。
5. 權限使用既有 `threads_basic`、`threads_content_publish`。公開應用程式資格、App Review、測試帳號存取，以本人後台當日結果為準。
6. App Secret 顯示時停止瀏覽器自動化／截圖，由本人放入本機精靈的隱藏輸入。最後官方 OAuth 登入及同意也必須交回本人。

## 真實實測狀態與故障排查

已實測：本機加密儲存、全新專用 DB、可驗證 TLS upstream、ngrok HTTPS、公開 UI、Callback 拒絕無效 state、停止／重啟與重跑保留金鑰。實際網址只保留在本機 `.threads-local/status.json`，避免把開發服務網址提交到公開 Git。

**仍缺 App ID／Secret、Meta Redirect 登錄與本人官方登入。SETUP_READY=false、OAUTH_VERIFIED=false、PUBLISH_VERIFIED=false。** LOCAL_SETUP_READY=true 只表示本機和 HTTPS 路徑可用。

| 訊息／現象 | 修復 |
|---|---|
| Docker command failed | 開啟 Docker Desktop，確認引擎及目前帳號存取權；不要改用客戶資料卷 |
| INSTALL_DOCKER_AND_NGROK_FIRST | 安裝官方工具並重新開啟終端 |
| ERR_NGROK_… | 依 [官方錯誤目錄](https://ngrok.com/docs/errors/) 檢查帳號驗證、token、免費額度或版本；不自動升級付費方案 |
| AGENT_PORT_IN_USE_BY_OTHER_TUNNEL | 4041 已有不同 agent；不會停止它，先由本人排除衝突 |
| EXISTING_VOLUME_WITHOUT_VAULT | 已有專用 volume 但 DPAPI vault 遺失；停止並找回備份，不生成新密碼覆寫 |
| DPAPI_FAILED | 使用原 Windows 帳號；不要刪舊金鑰，先還原受控備份 |
| API_TLS_READINESS_FAILED | 查看專用 Docker 狀態；TLS 不通時不能關閉憑證驗證繼續 |
| 公開 HTTPS 驗證失敗 | 檢查系統日期、CA、ngrok／網路；Windows 預設 CA 曾遇過期鏈，本程式改重用既有 HTTPX 的嚴格 CA 驗證，未使用 verify=false |
| OAuth URI 不符 | 重新執行精靈，將當次產生的完整 URI 重新登錄 Meta。此 ngrok agent 實測重啟後網址改變，不能保證固定 |
| --login 前未安裝 | 先執行正常精靈；登入視窗需要存活的專用 API 與有效公開網址 |

本精靈強制模型、發布與自動維護皆關閉；安裝或 OAuth 成功均不會公開貼文。正式發布與 Production 另行驗收。

官方資料查核：2026-10-26，[ngrok CLI](https://ngrok.com/docs/gateway/agent/cli)、[Agent API](https://ngrok.com/docs/gateway/agent/api)、[免費方案限制](https://ngrok.com/docs/pricing-limits/free-plan-limits)、[Meta 官方範例](https://github.com/fbsamples/threads_api)、[Meta 官方 API collection](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)。免費方案文件包含預設 dev domain 及瀏覽器提示頁；本機舊版 agent 的實際網址變動已另行記錄，不能以文件推定帳戶方案、固定網址或帳號權限已驗證。
