# MOS-PUB-002 安全與實作審查

來源 `2d653c0475fa840ca7ce0458ee601f3c3869f4b9`，分支 `codex/marketing-ai-os-threads-connect-ui`。保留 MOS-PUB-001 Adapter、加密 Token、OAuth nonce/state、Publication 狀態機、RLS、immutable Revision、A21 及 Ledger。

新增 browser_session／social_ui 與原生 HTML/CSS/JS。無前端框架、npm build、SDK 或新增 Python 依賴。IBM Plex Sans 本地字型是 SIL OFL 1.1，授權在 app/web/FONT_LICENSE.txt；中文使用系統字型。無第三方執行時資源請求。

- Cookie 工作階段重用既有 hashed、expiring、revocable MOS Credential。HttpOnly／SameSite=Lax；HTTPS 使用 Secure；HTTP 僅明確 test/development loopback。一般 API Bearer 相容保留。
- Cookie 寫入需同 origin 及 HMAC CSRF；登入也檢查 origin。管理員獨立一小時簽章 Cookie；owner、worker 不等於系統管理員。後端 MOS_ADMIN_KEY 登入不是 Meta App Secret。
- 前端不持有 Token，不使用 localStorage/sessionStorage，不顯示 App Secret。CSP self-only、無 inline script、禁止 framing、no-store/no-referrer。access log 繼續停用，避免 callback query／Token 洩漏；既有 Log 遮罩維持。
- UI 發布路由只編排原有 owner authorize + 同 tenant active worker execute，仍經相同權限、Revision/hash、開關、官方即時檢查與 durable dispatch marker；沒有直接 Provider bypass。首次與每篇均需要明確 confirm_public_post=true。
- 維護使用同 tenant lock，刷新前持久化 next_maintenance_at 和 IN_PROGRESS；重複排程跳過，崩潰後凍結。失效或權限／帳號錯誤即 REAUTH_REQUIRED + publishing=false。Migration 0010 僅新增 nullable 診斷欄位／預設計數，沿用既有 RLS，不刪資料。
- HTTPS 探測僅使用管理員部署的固定公開 callback，無客戶端 URL；五秒、TLS 驗證、無 redirect、無環境代理。探測不能證明 Meta 審查或官方授權。
- Preview 使用忽略的獨立合成 SQLite，測試 fixture 禁止真實 HTTPTransport；CI 所有 Threads 功能旗標 false。正常啟動不會發文。

限制：管理員 Cookie 是單機短效簽章，刪除瀏覽器 Cookie 不代表可撤回被竊取的副本；輪替 MOS_ADMIN_KEY 可全數失效。封閉式環境仍需受控管理員發碼與密鑰保管，正式營運前應完成成熟身分接入、管理員逐 session 撤銷與獨立安全驗證。頁面告警不等同外部監控。沒有測試真實 Meta 權限撤銷延遲或外部 exactly-once；未知發布結果保守凍結。
