# MOS-P1-001 實作紀錄

日期：2026-10-25 Asia/Taipei。來源 `codex/marketing-ai-os-p0-5-readiness` / `0ff9fc22543d79478d7cc819a9d7a59610c28e5d` 已核對，工作目錄乾淨後建立 `codex/marketing-ai-os-p1-agent-runtime`。main/develop/P0/P0.5 未修改；僅離線、受控、合成資料。

完成一條 A09 Threads 文案工作流，無真實 AI 或平台請求：

1. Owner/manager 沿用 POST /tasks 建立 A09 DRAFT。
2. tenant-bound worker 使用 POST /tasks/{task_id}/agent-run 提交結構化品牌／任務與 idempotency_key；owner/reviewer 不能冒充 executor。
3. A01 規則驗證 agent/platform/model/tools allowlist，只選 A09_THREADS_MOCK；未實作 known agent/platform 回501 NOT_IMPLEMENTED，未知 agent／非法model/tools／自報tenant_id回422。
4. 只載入 agents/A09/system.md 與 skills/threads-copywriting/SKILL.md，構成分層 prompt。估算輸入及最大輸出，A23 重用既有 reserve/claim/settle Ledger。
5. 最多一次 Mock generation。A21 用 Pydantic與Python規則檢查，不再呼叫模型；成功或 QA 失敗都保留結果並等待 owner 審核。
6. Owner 可明確 approve 後進既有 MANUAL_REQUIRED queue；沒有真正發布能力。

## 啟用及使用

預設仍 MOS_MODEL_CALLS_ENABLED=false。只有合成測試／開發可暫時設 true；**同時保持 MOS_LIVE_TESTS=false、不要設定任何真實 provider key**。新 agent-run 程式硬編 allowlist 到 Mock，沒有 client 可選 live provider 或付費 fallback；Anthropic 原有 enabled/live-key guard 未變。

依 README 做本機 bootstrap、管理員發行 owner/worker 身分，然後以 worker Bearer 呼叫新 endpoint。輸入 fixture：agents/A09/evals/threads.json，把 task_id 換成 owner 建立的 task ID。tenant_id 不在 request schema，由認證取得；不得加進內容冒充授權。

新增查詢：GET /tasks/{id}/agent-run（read scope、同 tenant）；GET /agent-runtime/capabilities。前者包含私有 prompt 與完整結果，只能授權人員讀取。所有既有 API 保留；/budget 增加 mock_spent_usd/non_mock_spent_usd 供區別。

```powershell
$env:MOS_LIVE_TESTS = 'false'
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m mypy
.venv\Scripts\python -m compileall -q app tests migrations scripts
.venv\Scripts\python -m pip_audit -r requirements-dev.txt
```

## Schema 與相容性

0004 只增加 nullable Task.agent_run JSON；原 task RLS、composite FK、immutable rate snapshot、cost/audit triggers 不變。既有資料不用回填假 run metadata；本次只在全新合成 PostgreSQL volume 測試。schema head/readiness 預期從0003更新0004；舊測試及 scheduler smoke 只調整這個版本斷言，沒有刪除安全測試。

A01–A24 仍為靜態註冊 profiles，舊 status REGISTERED_NOT_EXECUTING 表示沒有常駐角色程序，不反映單一 task state。A09 額外 executor=THREADS_MOCK_ONLY；A01/A21/A23 額外 rule_role。只有 A09 有 executor，沒有24個常駐 processes。

新增依賴：0。沒有 OpenAI adapter 實作、RAG、Agent framework、workflow engine 或額外模型呼叫。遠端 CI 最終結果見 P1_TEST_EVIDENCE；未取得本分支成功前不宣稱 PASS。
