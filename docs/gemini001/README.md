# MOS-GEMINI-001｜Gemini 免費層接入

查核日期：2026-10-28。功能接到現有 `/app/automation`、加密政策 Key、Task、A09、A21、Revision、單次許可、整數 micro-USD Ledger 及排程。無新增套件／服務／資料表，沒有 Schema Migration。

## 官方規格與選型

- 穩定文字模型：`gemini-3.5-flash-lite`。[模型清單](https://ai.google.dev/gemini-api/docs/models)、[模型規格](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)。官方標示 Stable、支援文字及 Structured Output。MOS 主動限制 4096 輸入／1024 輸出 Token；不是 Google 完整上下文上限。
- [官方費率](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite)：Standard 免費層輸入與輸出免費；付費層文字輸入 USD 0.30、輸出（含 thinking）USD 2.50／百萬 Token。MOS 沒有實作付費 Gemini、工具、搜尋、快取寫入、批次或模型 fallback。
- [計費說明](https://ai.google.dev/gemini-api/docs/billing)：Key 繼承專案計費狀態；Free 與 Paid 不是由模型名稱或 API Key 格式判斷。免費層資料可能用於改善產品，UI 明示，只用可提供的品牌資料。
- 使用既有 HTTPX；不用新增 SDK。POST [generateContent](https://ai.google.dev/api/generate-content) 與 [countTokens](https://ai.google.dev/api/tokens)；Key 僅在 `x-goog-api-key` Header，禁止放 URL。單一候選、JSON Schema、minimal thinking，輸出上限含 thinking；STOP 以外結果不可當成有效完成。

## 使用方式

1. 原自動化中心 → 第 2 步「連接 AI」。選取已存 AJ 政策，Provider 選 Google Gemini，按「沿用品牌，建立 Gemini 設定」。原 OpenAI 政策、Key 與品牌不變。
2. 在受信任 MOS HTTPS 頁面保存 Gemini Key。成功清空密碼欄並顯示綠色成功；失敗保留輸入與原因。草稿可更換 Key，更換後舊免費驗證失效。
3. 「測試 Key 連線」只 GET 官方模型 Metadata；通過不代表免費資格已驗證，不會生成。
4. 進階免費資格：輸入 Project ID、Key 資源名稱與 Google 短效存取權杖。權杖只在本頁記憶體／這次後端請求使用，不進資料庫、Vault、回應或 Log。管理者可在可信任 Google Cloud Shell 執行 `gcloud auth print-access-token`，僅貼到 MOS HTTPS 密碼欄，不貼聊天；需有下述唯讀 IAM 權限。不要為此開通帳單。
5. 唯讀驗證通過後，再另行確認第一次真實生成；本次部署 `MOS_GEMINI_FREE_CALLS_ENABLED=false`，尚未執行真實生成。未來經使用者批准可單獨開啟免費開關，OpenAI 的 `MOS_MODEL_CALLS_ENABLED` 仍可維持 false。每次測試還需要 UI 明確確認並建立持久化的一次性許可，走原 `/ai-tests/{id}/execute`。

## 免費資格的證據與阻擋

只靠 AI Studio 顯示 Free 或使用者勾選不夠。官方唯讀檢查：

- [Resource Manager projects.get](https://docs.cloud.google.com/resource-manager/reference/rest/v3/projects/get)：綁定 Project ID、數字編號與 ACTIVE 狀態。
- [API Keys getKeyString](https://docs.cloud.google.com/api-keys/docs/reference/rest/v2/projects.locations.keys/getKeyString)：在後端常數時間比較，確認加密保存的 Key 真正屬於該專案，絕不回傳 Key 字串。需要 `apikeys.keys.getKeyString`。
- [Cloud Billing getBillingInfo](https://docs.cloud.google.com/billing/docs/reference/rest/v1/projects/getBillingInfo)：必須明確 `billingEnabled=false` 且未連結帳單。需要 `resourcemanager.projects.get` 與適用 OAuth scope；權限不足／欄位缺失／已連結但暫停的帳戶都拒絕。

連線證據限 10 分鐘並綁 Tenant、政策 Hash、Key 指紋、專案設定版本。每次 count／generate **重新**執行官方計費與 Key 對應檢查；不是永久快取免費資格。短效驗證權杖到期必須停止；目前沒有新增長期 Google 登入／權杖刷新系統。每日無人運行仍需另行配置可持續更新的受控後端唯讀權限，不把短效驗證冒稱永久完成。

Google 未提供本程式可用的「強制免費且禁止外部啟用計費」請求參數。外部管理者在檢查後同時啟用帳單的競態仍存在；應使用專用、未連結帳單專案並限制誰能修改計費。不能宣稱本地檢查可保證任何外部帳戶變更下永遠零帳單。

## 資料與成本安全

- 政策條款仍不可變。專案設定、連線證據與單次測試使用現有 AITestPermit 的 JSON kind，唯讀紀錄沒有生成批准、保持不可執行狀態；不增加資料表。一般付費批准端點不能將這些紀錄轉成可執行許可。
- 只新增一筆不可變 Gemini FREE_ONLY 費率紀錄。`python -m scripts.install_gemini_rate` 使用既有 migration role 附加安裝；runtime role 仍無權寫 rate_versions。不覆寫歷史費率。正式 Schema 維持 0015。
- 既有 ReserveRequest 不允許零預留，因此暫留 **1 micro-USD** 作為准入安全餘額，免費 Mock／已核實免費層試算結算為 0 並釋放預留；預留不是實際支出。Provider usage、thinking、Mock 用量與發票分開；沒有 Invoice 就不標記已驗真。
- 同次請求持久化佔用一次名額；重複／並行執行不重送。429、timeout、5xx、不明用量／費用停止並待處理，沒有 OpenAI fallback。未知結果凍結後續單次測試。
- AJ 沿用現有 320～450 字元風格建議，Gemini 政策硬上限 480；QA／無依據宣稱與人工審核邊界不放寬。Gemini 語意審查不能轉用付費 OpenAI。

## 測試與部署

- `tests/test_gemini.py`：19 項 Mock／HTTP／資料庫測試，含 Key 加密與更換、免費驗證、付費／錯誤專案拒絕、配額、逾時、5xx、截斷、錯誤 usage、並行去重、預算及 QA、既有排程管線、跨租戶與敏感資料遮罩。
- 既有 OpenAI／MVP 針對性回歸 59 項通過；本機完整 SQLite 回歸 524 passed、2 skipped、1 deselected（Windows 環境）。最終 SHA 的 PostgreSQL、mypy、漏洞掃描及完整回歸以 GitHub Actions 為準。
- 真實瀏覽器 1440／768／390 寬度：AJ → 保存 OpenAI 合成 Key → 建立 Gemini 設定 → 原設定不變 → Key 保存 → 唯讀模型檢查 → 合成免費證據 → 明確確認一次 Mock 生成。`ui/evidence.json`、三張畫面；不是實體 iPhone Safari，也不是真實模型品質驗收。
- 重跑：啟動 `tests/gemini_browser_fixture.py`，設定 `MOS_CDP_HELPER` 為現有 CDP helper 的 file URL，再執行 `node tests/gemini_browser.mjs`。僅 localhost 合成資料。
- 部署先備份 DB／原容器／Recovery 設定；以 migration role 附加費率後替換 API 映像，保留原 Volume、Token、Vault、環境開關與固定網域。回復可切回原映像；新增不可變費率可保留，不需要刪除資料或降版 Schema。

本次真實 Gemini 生成 **0 次**，真實 Threads 貼文 **0 篇**，實際模型 API 費用 **USD 0**；無新增付費服務。帳戶 Key／免費資格尚須由使用者在安全 UI 配置並官方實測，不宣稱全自動發文已驗收。
