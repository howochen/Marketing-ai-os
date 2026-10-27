# MOS-AUTO-001 驗收

日期：2026-10-27。基準 `1f4ad7e8c775f396358018e804ad486a9871bc9b`；開發分支 `codex/marketing-ai-os-threads-automation`。

**離線開發驗收與真人驗收分開。** 本次可執行政策 → 排程名額 → A09 → A21／素材限制 → 原 Ledger → 精確 Revision → 原兩階段 Publisher → 合成讀回。FULL 流程不建立假的 Owner 單篇批准，REVIEW 必須先批准指定版本。

| 實測 | 證據 |
|---|---|
| Windows SQLite 全套 438 passed、2 skipped、1 deselected | auto001/sqlite.txt |
| Docker PostgreSQL 全套 434 passed、6 skipped、1 deselected | auto001/postgres.txt |
| 最終變更後針對性 SQLite／Provider 回歸 | auto001/focused-final.txt |
| 最終 migration 從空白獨立 PostgreSQL 重跑政策／發布／內容／RLS 回歸 | auto001/postgres-final.txt |
| mypy 33 檔 | auto001/mypy.txt |
| 固定依賴掃描，無已知漏洞，沒有新增套件 | auto001/audit.txt |
| Docker tests image 實際建置 | auto001/postgres.txt、postgres-final.txt |
| 25 表合成備份還原，0 筆快照遺失、4 項負面檢查，0600／0700 | auto001/backup-restore.json、backup-drill.txt |
| 真實 Chrome 1440／768／390px，無水平溢出；手機尺寸實際表單保存政策 | auto001/ui/browser-evidence.json 與 PNG |
| JS 語法、git diff --check | 本機檢查及最終提交 CI |

SQLite 兩項略過為 PostgreSQL 專屬隔離測試；PostgreSQL 六項略過為 Windows 原生 Cmd／Tk／DPAPI，Windows 本機與 CI 另外執行。付費 Live 測試排除。既有 Starlette/httpx deprecation warning 保留，沒有為本階段擴大升級依賴。

測試包括全流程不需逐篇發布、半自動精確核准、手動模式保留、上限／QA／未知語意阻擋、Owner 權限、跨 Tenant、政策替換／撤銷、狹義 Worker 拒絕通用管理／執行端點、Owner 登入到期後仍可依政策工作、兩 Worker 唯一 slot、生成／發布未知結果不重送、不補發、刷新不是重新授權、加密 Key／Worker grant 不洩漏、政策 DB 不可覆寫與 PostgreSQL RLS。

第一次合成端到端被既有 publication_content_guard 正確擋住。0014 保留舊 guard 的人工批准路徑，新增精確政策 slot 的替代授權。初版 UI 把帳號 API 陣列誤作物件已由真實瀏覽器測試修正；SQLite 日期缺時區造成的八小時偏移也已修正並加入回歸。

## 真正可用與未啟用

- 可用：政策建立／版本／Owner 確認／暫停與撤銷、加密 Provider Key、狹義 Worker、持久化排程、生成與費用流程、QA／素材／近似重複檢查、單篇審核相容、兩階段 Publisher 重用、結果追蹤、繁體中文中心及手機尺寸操作。
- 有意限制：FULL 只能用 Owner 預先核准完整段落組文，不是無限制的新事實自主創作；高風險或未知語意轉人工。選題是規則挑選，不是市場研究；自動重寫 0 次，失敗不再花費。
- 未啟用：原 DB 0013／0014、現有公開 API、真實模型傳輸 Release Gate、真實發布及持續政策服務、手機秘密通道。不能以政策授權自動解除 Live Gate。
- 尚待部署驗證：Windows 重開機／Docker Desktop 無人登入啟動、實體 iPhone Safari、本人 OAuth／Token 有效性、Provider 帳戶權限、真實 Token／成本、真實發布 ID 與官方連結。
- 前階段 Privacy Callback 現行官方契約仍 NOT_VERIFIED；本次只修復與自動化直接相關的授權／刷新時間判斷，不重新開發該專案或宣稱其可公開。

## 成本與資源

真實 AI API 呼叫 **0**，實際模型 API 費用 **USD 0**，真實 Threads 貼文 **0**。沒有新套件或付費服務。

UI 合成示例成本為 **USD 0.003528 模擬值**（依既有 Mock bytes 與歷史費率快照），不是 Provider Token、帳單或真實支出。Provider Mock HTTP 的 usage 也只屬合成回應。帳本保持整數 micro-USD、不可變 RateVersion 與 UNVERIFIED 收據，不製造 Invoice。

新增常駐負擔僅在將來批准後的一個 Tenant Worker（重用現有 runtime image、30 秒輪詢，無公開 port）。本次測試使用獨立 mos-auto-test PostgreSQL volume；沒有動原資料卷，停止測試服務時保留 volume。沒有 24 個 Agent process、向量 DB、Kafka、Celery 或 Kubernetes。

使用方式與流程圖見 [操作說明](AUTO001_GUIDE.md)，正式部署與每一層需批准的事項見 [部署計畫](AUTO001_DEPLOYMENT.md)。最終 CI 以交付 Commit SHA 對應的遠端 GitHub Actions 紀錄為準，不能用前一個 SHA 或本機成功替代。
