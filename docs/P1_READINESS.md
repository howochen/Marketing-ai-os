# P1 準備規劃 — MOS-P0-009（文件，未實作 P1）

目前建議：**不開始 P1 功能**。P0 離線驗收通過，但無付費收據、正式平台權限、備份復原及公開服務安全證據。可以先審閱本文件與基礎設施待辦，任何下一階段開發另行授權。

## 可直接重用

- app/registry.py 的 A01–A24 capability profiles；不是已運行 agent。
- app/security.py 的 tenant-bound role AND scope、hashed expiring/revocable credentials。
- app/database.py 的 transaction-local scope，models 的 composite FK、Alembic 及強制 RLS。
- app/main.py 的整數 micro-USD reserve/claim/settle/release/recover、owner approval、idempotent manual publication queue。
- app/providers.py 的 LLMProvider Protocol、單一 Anthropic adapter、usage_cost、feature flag；app/adapters.py 的 manual_only 社群 Protocol。
- 既有 PostgreSQL／SQLite suite、ThreadPoolExecutor 並行回歸、Docker Compose 與 CI jobs。

## 尚缺必要基礎設施

有驗證的 identity/delivery provider、rate limits／abuse protection、HTTPS與secret管理、受限 worker 部署／失效撤銷策略、recovery 排程／監控告警、受控 backup/restore 演練、依賴版本鎖定與patch流程、不可變費率歷史／發票驗真、遠端 CI 成功證據。真實平台 connector 需另有 provider permissions 與 webhook 簽章／去重設計，未具備時維持 manual_only。

## 正式 Agent 執行最低要求

先只啟用一個 registry agent：驗證輸入與 agent_id、授權到特定 tenant、明確模型／工具 allowlist、預留最壞成本後唯一 claim、deadline/token/output/tool-call 上限、secrets 不進 prompt/log、保存 usage/message ID／錯誤分類、未知結果不得盲目 retry、具體可重現 eval/整合測試。結果仍為待審草稿；內容不得自行宣布發布或產生營收。先評估單一 worker process，無需為 24 個 profiles 啟動 24 個服務。

## 模型 API Adapter 建議

沿用 LLMProvider count_tokens/generate 與 HTTPX。最小擴充是具明確欄位的 request/receipt 資料結構：provider/model、request/message ID、usage 各類 token、rate-card version、deadline、stop reason。adapter 只做供應商傳輸／格式轉換；shared ledger 保留授權、budget、idempotency及settlement責任。區分明確未提交的錯誤與已可能計費的 timeout；只有前者可有受限 retry。先補 mock contract tests，再由使用者明確授權的低額 live integration 證明收據，不在本工單執行。

## Token 預估與實際計費

count_tokens＋max output 只是執行前上界，reserve 不等於 spend；實際 receipt usage 才進 settle。cache read/write、reasoning、tools、regional tiers 等需按對應供應商規格明確記錄，不能將所有輸入乘一個價。實際額超 reserve 仍要記帳並暫停新花費，不可隱藏已發生帳單。每月 token quota 是獨立需求，目前不存在，不能由美元 budget 反推成已實作。

## 費率版本更新

目前只有 config/models.json 本地生效日與官方 source URL。規劃新增 immutable rate-card versions（provider/model/currency、rates、effective-from/to、verified-at、官方來源）；由人工審核變更及離線 fixture 測試，拒絕無來源／重疊生效時間。reserve snapshot 與 receipt settlement 固定參照當次 version，舊帳不隨 JSON 更新而重算。到期／來源未覆核時停止新執行；不要在每個請求抓 pricing 網頁，也不要編造 price ID。

## Agent Router 方案

先用一個明確的 allowlist mapping：agent_id → 已登錄 executor / model policy；先檢查 tenant/role/scopes，再驗證輸入、估算、reserve、claim、執行、settle、待 owner approval。未知 agent／未實作 executor 一律拒絕，不自動 fallback 到另一個付費模型。router 不收費、不直接發布；重用現有 task 狀態與 tenant budget，失敗依現有 reconciliation 流程處理。只有真實併發與可靠性需求證明不足時才考慮 durable queue。

## 重用工具與避免複雜化

優先重用 Python stdlib、FastAPI／Pydantic、SQLAlchemy／Alembic、PostgreSQL、HTTPX、pytest、pip-audit、GitHub Actions；備份用 pg_dump/pg_restore 或 SQLite backup API。使用現有開源套件與來源／license log，不為數行程式加依賴。Docker Desktop host 授權與 CI quotas 另依帳號確認，不宣稱一律免費。

暫不建議 Kubernetes、service mesh、每 agent 一個微服務、Kafka、向量庫／RAG、動態多 agent 自我路由、通用 workflow DSL、同時多家供應商自動 failover、複雜 event sourcing 或 heavyweight agent framework。先以現有模組完成一個受限可對帳的端到端流程，再以數據決定是否需要新架構。
