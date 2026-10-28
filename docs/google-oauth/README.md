# Gemini Google 官方登入整合

一般操作入口：https://metathetic-nonlyric-lana.ngrok-free.dev/app/automation → 連接 AI → Gemini → 連接 Google。

## 管理員一次性設定
Google Web OAuth Client 與 Gemini API Key 不同，不能由已保存的 API Key 推導。至既有 /app/admin#google-oauth-setup，使用管理員安全通道保存 Google Web Client ID / Secret；Secret 加密保存，不回傳。Google Auth Platform 必須登記：

`https://metathetic-nonlyric-lana.ngrok-free.dev/google/oauth/callback`

設定同意畫面及測試使用者。唯讀範圍 cloud-platform.read-only、cloud-billing.readonly；使用者仍須有相應專案/IAM 權限。MOS 不代替 Google 審核或使用者同意。

## 正常流程與限制
按連接 Google → 官方同意 → 同一瀏覽器回到 MOS → 自動查詢專案及已保存 Key → 核對未連結計費帳戶、模型免費費率。多專案只需下拉選擇，不複製 Token、不輸入資源名稱。狀態為免費層已確認／待確認／不符合資格；錯誤、缺權限、撤銷或計費未知均停止產文。

後端以 state、Secure/HttpOnly cookie、PKCE S256、Owner/Tenant 綁定、10 分鐘及單次消耗防重放。授權碼不重試。存取及刷新 Token 沿用既有加密；使用既有 append-only AITestPermit 審計紀錄，不新增 Migration。刷新前先持久化 pending，未知失敗需重新連接，不盲目重送。登出不撤銷既有狹義授權；撤銷、停用租戶、政策到期或 Key/Client 變更使其失效。每次產文仍重新核對免費資格，不代表授權產文或發布。

Google External App 處於 Testing 時，這些範圍的 refresh token 可能 7 天到期；正式長期使用須符合 Google 發布及驗證條件。無法保證永久免重新授權。

## 驗收
隔離 HTTP OAuth 整合 10 項通過，涵蓋 PKCE、加密、單次狀態、拒絕、重放、跨租戶、登出後刷新、刷新撤銷、交換中撤銷、無手動 Token 的 Mock 單次產文。mypy 39 模組通過。
瀏覽器 1440/768/390：真實 UI 點擊＋攔截 Google 跳轉＋Mock Token/Google API，回呼自動免費檢查成功，無手動 Token/資源欄，無水平溢出。證據 ui/evidence.json。這些不是本人 Google 官方授權實測。

正式 Windows 部署：不變更 Schema、政策、加密 Gemini/OpenAI Key、Threads Token、DPAPI、固定網址或停用開關。真實生成及發文 0 次。

官方來源（2026-10-28 查核）：
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/identity/protocols/oauth2
- https://ai.google.dev/gemini-api/docs/billing

剩餘阻擋：若尚未配置 Google Web OAuth Client，登入按鈕保持關閉；實際免費資格需 Client 配置及本人官方同意成功後確認，不能以 Mock 宣稱已通過。
