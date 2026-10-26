# Threads 手機優先：首次初始化與日後連接

> 2026-10-26 更新：預設雙擊已改成 Windows Callback 優先精靈。手機交接必須明確加 --mobile，且後端設定通過才提供登入。下方保留原手機階段的歷史驗收與限制；目前規則見 THREADS_SETUP_FLOW.md。
2026-10-26 實際檢查：HTTPS／公開 UI／Callback 可用，加密 key 與 Docker 已具備；**運行中的後端尚未配置 Threads App ID／App Secret**。Meta Redirect 登錄與本人官方 OAuth 未驗證，沒有真正 Threads ID。Facebook Login 或 Chrome 設定檔登入不能代替 Threads App 設定。

`Setup-Threads.cmd` 已預設手機模式；`--mobile` 可明確指定，原 Python CLI 的桌面相容模式仍保留。沒有使用 Computer Use 或操作任何 Chrome 設定檔。

## 一次性管理員初始化

1. 管理員在 iPhone Safari 開啟 https://developers.facebook.com/apps/，以正確 Meta 身分登入。優先沿用已有、具 Threads API use case 的 App；不要重複建立。若手機後台版面不完整可使用 Safari「要求桌面版網站」。密碼、MFA、審查與本人同意由本人完成。
2. 確認 **Threads 專用** App ID／Secret、`threads_basic` 與 `threads_content_publish` 的資格，以及指定 Threads 測試帳號已接受邀請。App Review／政策要求以官方後台為準，不能自動宣稱完成。
3. Secret 管理通道沿用 **Windows 本機受控終端隱藏輸入 → 當前使用者 DPAPI → 既有 Docker 後端**。在可信任的 Windows 電腦執行：

   ```powershell
   .\Setup-Threads.cmd --mobile
   ```

   輸入 App ID；Secret 只在隱藏提示輸入，不貼聊天、URL、普通表單或截圖。首次初始化仍需這個本機管理步驟；沒有新增手機一般網頁 Secret 表單。可由同一位管理員看手機官方後台後在本機輸入，不能請不受信任的人代收。
4. 精靈自動配置後端並顯示完整 HTTPS Redirect URI。把它原樣保存到 Meta 的 Threads OAuth Redirect Callback URLs，再核對；不是 Webhook Callback。實際網址見本機 `.threads-local/status.json`，不提交 Git；ngrok 網址變動需重新登錄。
5. 手機模式顯示 iPhone 入口與既有十分鐘一次性 **MOS 工作區**登入碼，不開 Windows Chrome，不把碼放 URL、不另造登入機制。MOS 工作區登入與 Threads 官方 OAuth 是兩個不同步驟。

## iPhone 與未來一般使用者

1. 在 iPhone **同一個 Safari 正常分頁**開啟精靈顯示的 `https://…/app/threads`。不要在 LINE／Facebook 內建瀏覽器與 Safari 之間轉貼 OAuth URL。
2. 登入原有 MOS 工作區；若已登入則直接進入。初次管理員交接使用本機視窗顯示的一次性碼，可用 iPhone 原況文字讀取後貼入原有登入欄，勿貼聊天。重新取得碼用 ` .\Setup-Threads.cmd --login --mobile `。
3. 點「連接 Threads 帳號」，在官方頁面登入本人 Threads 並核對同意內容。官方 OAuth 開始、nonce Cookie 與 callback 必須留在同一瀏覽器脈絡；不手動交換 Token。
4. 返回既有 UI 後，系統由官方 API 核對帳號 ID、username、scopes、到期時間並加密綁定 tenant。用「檢查連線」或 Windows ` .\Setup-Threads.cmd --diagnose ` 做新官方驗證。只有實際成功才 OAUTH_VERIFIED；Mock／Facebook 登入／網頁 HTTP200 均不算。
5. 未來其他使用者不再配置 App Secret 或 Docker，只需登入自己的 MOS 工作區，點「連接 Threads」並完成官方授權；仍須具備 App 允許的帳號資格。**不取消 tenant RBAC、一次性登入或人工審核。**

## 目前阻礙與驗收

- 缺少已配置的 Threads App ID、App Secret。
- 尚未核對 Meta 後台已保存當次 Redirect URI、Threads 測試角色與權限。
- 本人尚未於 iPhone 執行官方授權，真實 ID／username／scopes／expiry 尚無證據。
- 實際 iPhone Safari 端到端驗收未完成；既有跨瀏覽器／state／nonce 防護不放寬。

保留既有 Adapter、OAuth、DPAPI、ngrok、Docker、UI；只在原本初始化器新增手機交接選項，無新依賴、無新 Mock 登入頁、無 Secret 網頁 API。發布與模型旗標保持 false；未發文，OAUTH_VERIFIED=false、PUBLISH_VERIFIED=false，整體 PARTIAL。

官方核對來源：[Meta Threads API collection](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)、[Meta 官方範例](https://github.com/fbsamples/threads_api)，2026-10-26。官方 collection 明確區分 Threads 專用 ID／Secret，Redirect URI 必須與發起授權時一致。

本次驗證：安裝器26項、合併既有 UI／OAuth／發布回歸共76項通過；mypy25模組、compileall、diff --check 通過。實際開啟手機交接視窗，程式不自動開 Windows 瀏覽器；秘密與登入碼不進 URL。手機 Safari 官方端到端仍須本人完成後才能驗收，以上離線測試不代替 OAUTH_VERIFIED。
