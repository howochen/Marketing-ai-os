# Gemini 免費設定 UX 改善

查核日期：2026-10-28。沿用原 Gemini Provider、加密 Key、AITestPermit、政策、QA、Ledger 與免費模式；無新資料表、Migration、套件或服務。

## 一般操作

1. 在既有「連接 AI」保存 Gemini Key；已有 Key 不需要重填。
2. 按「開啟 Google 官方授權（臨時驗證）」。已預填 cloud-platform.read-only 與 cloud-billing.readonly。按 Authorize APIs、登入建立 Key 的帳號並同意；再按 Exchange authorization code for tokens，將 Access token 貼回 MOS 安全欄位。不是 Gemini API Key、Refresh token 或 Google 密碼。
3. 按「讀取我的 Google 專案」，從清單選擇 AI Studio 專案，再按「自動找出 Key 並確認免費資格」。不需查找 Project ID 或 Key 資源名稱。
4. 顯示三種狀態：免費層已確認、待確認、不符合免費資格。只有新鮮的官方免費證據才可申請生成；仍須原本單次生成確認與安全開關。

本站尚未配置並接入自己的 Google OAuth Web App，沒有宣稱本站已完成一鍵 OAuth。這次使用 **Google 官方 OAuth 2.0 Playground** 作為臨時驗證的備援：MOS 不自行交換 Google Authorization Code、不接收 Refresh token，也沒有新增 Callback。本人登入與同意仍必須由使用者完成。

Google 官方工具的公開頁面及預填 scopes 已在無登入隔離瀏覽器確認；**尚未替使用者登入或驗證其真實 Google 帳戶**。Google 若拒絕授權或 IAM 權限不足，保持待確認，不繞過。

## 官方依據

- [Google OAuth Web Server 流程](https://developers.google.com/identity/protocols/oauth2/web-server)：本站直接授權需要登記 OAuth Client／Redirect URI；現環境沒有相關 Client 設定。
- [官方 OAuth Playground](https://developers.google.com/oauthplayground/)：使用 Google 預設端點、Server-side flow；不要使用自己的 OAuth credentials，也不要建立含 OAuth Token 的分享連結。[公開程式碼](https://developers.google.com/oauthplayground/assets/js/ui_logic.js) 與無登入實際頁面確認可透過 scopes fragment 預填唯讀權限，連結不含任何 Key 或 Token。
- [Projects.search](https://docs.cloud.google.com/resource-manager/reference/rest/v3/projects/search)：讀取有權檢視的專案；最多列出 100 項，截斷時明示。
- [Keys.list](https://docs.cloud.google.com/api-keys/docs/reference/rest/v2/projects.locations.keys/list) 與 [GetKeyString](https://docs.cloud.google.com/api-keys/docs/reference/rest/v2/projects.locations.keys/getKeyString)：只在使用者選定的專案檢查最多 20 個 Key，在後端常數時間比較，不回傳 Key 字串。超過上限或權限不足改由進階指定，不推斷通過。
- 不使用 LookupKey，因其 keyString 是 query parameter；Key 與 OAuth Token 不得出現在查詢網址。Google Token 始終是 Authorization Header，Gemini Key 始終是 x-goog-api-key Header。
- [Cloud Billing](https://docs.cloud.google.com/billing/docs/reference/rest/v1/projects/getBillingInfo)：沿用每次生成前的計費核對。明確已連結帳單標示不符合免費資格；缺欄位、無權限、驗證過期或 Key 改變標示待確認。

## 失敗時的指引

主要頁提供 Google 官方授權步驟、唯讀 scopes 複製按鈕與 Key／資源名稱／OAuth 權杖差異表。Cloud Shell 僅為次要備援；管理員手動 Project ID／Key resource 欄位預設收合。

如果專案不出現：先核對 Google 帳號與 projects.get 權限。自動找不到 Key：檢查選定的專案與 keys.list／keys.getKeyString 權限。短效權杖過期：重新由官方工具取得，只貼安全欄位，不貼聊天。不可為驗證而開通帳單。

## 安全與測試

- 沒有放寬免費資格或 Owner／Tenant 權限，沒有變更 Threads、品牌、原 OpenAI Key 或已存 Gemini Key。
- 新增兩個既有政策下的 Owner API：POST gemini-projects、gemini-discover。自動查找有 5 次／5 分鐘限制，固定 Google hosts，無任意 URL、模型生成或帳單操作。
- 專案資料與驗證證據沿用原附加式紀錄。權杖只留在當頁記憶體與該次後端請求，成功讀取專案後清空密碼欄；不進 DB／Vault／Log／一般回應。
- 免費資格 10 分鐘後介面自動降為待確認並停用生成按鈕；後端仍重查，不能只靠介面狀態。
- 本機 29 項 Gemini／品牌／政策測試通過，mypy 38 模組通過。測試涵蓋自動查找、未知與付費狀態不同標示、未知不得生成、跨租戶與 Secret 不洩漏。
- 實際合成瀏覽器驗證 1440／768／390 寬度、專案選單、Key 自動定位、進階欄位收合，以及原 OpenAI 政策／Key 不變。Google 授權與費率證據 Mock 皆明示合成；不是官方帳戶實測。
- Windows 部署先備份、只替換 API，保留資料庫、Token、Vault、固定網域及 Recovery 註冊。全部生成、發布與 Worker 開關保持關閉。完整 SQLite、PostgreSQL、漏洞掃描及備份演練以最終 SHA 的 CI 為準。

本次真實模型生成 0 次，公開貼文 0 篇，模型 API 費用 USD 0。實體 iPhone Safari 與本人 Google 同意尚需使用者驗證；臨時權杖不代表長期無人排程憑證已完成。
