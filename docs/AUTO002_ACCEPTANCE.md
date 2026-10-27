# MOS-AUTO-002 驗收（2026-10-27）

**核心離線功能完成；真人／公開部署驗收 PARTIAL，尚未授權執行。**
分支 `codex/marketing-ai-os-auto-core-fixes`；基準 `787d2544aa51a5ed716286a89a8ed86f406fd0a9`。
固定交付 SHA 以本文件所在 Git commit 為準，遠端 CI 必須核對該 SHA，不能沿用 AUTO001 成功紀錄。

## 實際功能證據

| 驗收 | 結果與程式位置 | 具體測試 |
|---|---|---|
| 一般登出後政策繼續 | PASS；social_ui logout reason、automation worker_policy；Session 仍401 | test_logout_ends_session_but_policy_survives_worker_restart、test_review_policy_keeps_exact_approval_after_logout |
| 政策／安全撤權停止 | PASS；main credential revoke 與 logout 相同 Tenant lock | 上述 logout test、test_security_revoke_after_logout_still_stops_policy、test_concurrent_logout_cannot_undo_security_revocation |
| 新 Hook／正文／CTA | PASS（Mock 能力契約）；BRAND_GUIDED 沒有 approved_copy，輸出新全文 | test_brand_guided_creates_novel_hook_cta_with_evidence_and_cost |
| QA／未支持宣稱停止 | PASS；固定規則及語意證據都必須通過 | test_creative_gate_fails_closed 的醫療、虛構門市、機械、stale hash、REVIEW、timeout 等案例 |
| 重寫成本與版本不消失 | PASS；AutomationAttempt→Task／Ledger，最多一次 | test_bounded_rewrite_keeps_all_versions_and_all_costs |
| 預算及未知結果停止 | PASS；Tenant cap、月 cap、permit cap、pending freeze | test_creative_requires_human_when_configured_and_budget_reserves_review、test_single_unknown_overrun_never_retries_or_truncates、test_one_shot_duplicate_consent_and_unknown_freeze_other_permit |
| 一次真實 AI 路徑 | 離線 PASS／Live NOT_EXECUTED；single_ai_test，兩方核對許可／帳戶／價格證據 | test_one_shot_records_usage_ledger_and_never_publishes、test_single_requires_two_authorities_flags_and_exact_tenant、test_unverified_count_endpoint_cost_cannot_be_approved |
| 並行、不可變、RLS | PASS；Tenant lock、DB constraints／triggers／FORCE RLS | test_parallel_single_permit_never_dispatches_twice、test_new_execution_evidence_is_immutable_and_tenant_scoped，既有 automation 並行測試 |
| 舊 Revision／OAuth／Token 安全 | 原回歸保留；沒有改 OAuth 或 DPAPI | test_automation、test_social_ui、test_threads_publisher、test_content_workbench、test_provider_readiness；CI 全套 |

所有新增核心案例在 `tests/test_auto_core.py`；測試呼叫真實 ASGI HTTP 路由及隔離資料庫，外部 Provider／Threads 一律 Mock。這證明流程與守門條件，不證明真實模型創作品質、官方發文或事實真確性。

## 報告與畫面

- SQLite：162項通過（`auto002/sqlite-verified.txt`）＋2項新增 DB immutable 與並行補充通過（`rls-sqlite.txt`、`concurrency-sqlite.txt`），共164項針對性回歸。
- PostgreSQL：162＋2項通過（`auto002/postgres-final.txt`、`postgres-extra.txt`）；非特權 runtime role，獨立 `mos-auto2-test` project 的 `mos_auto2_final`，全新從 base migration 至0015。
- mypy：`auto002/mypy.txt`（35個既有及新增核心檔案）；JS syntax、git diff check 通過。
- 漏洞掃描：`auto002/audit.txt`（無已知漏洞）；沒有新增或變更任何套件。
- Docker build 包含 PostgreSQL 測試；`auto002/compose-validation.txt` 確認未啟用 trial overlay 的預設關閉、loopback及獨立volume，沒有啟動該服務。
- `auto002/backup-restore.json`：27張合成表 snapshot 全部還原一致、0列遺失；backup 0.825秒、restore+verify 12.159秒；檔案0600／目錄0700，4項失敗情境。只是隔離 snapshot 能力，不保證正式 RTO／持續 RPO。
- `auto002/ui/browser-evidence.json`：1440／768／390px 無水平溢出；390px 實際點擊 form 建立 BRAND_GUIDED、HUMAN_REQUIRED 政策並寫入隔離 DB。這是桌面 Chrome mobile viewport，**不是實體 iPhone Safari 實測**。
- [手機政策畫面](auto002/ui/mobile-created-policy.png)。畫面明確顯示 Worker／Live 未啟用、Mock結果與待授權新政策。

## 使用與剩餘阻擋

既有 `/app/automation` → 建立政策 → 選「品牌規範自主創作」→ 填品牌事實 `ID|完整事實句|Owner來源` → 選待人工或模型語意審查 → 設0／1次重寫及原時段／預算 → 儲存 → Owner核對版本授權。
本次 UI 只在隔離 loopback 啟動測試，未套用原系統，既有公開網站不會出現新功能。原兩個 cmd 的既有工作區變動保留，沒有提交；前次 Privacy 規格查核文件保留、不納入本次 commit。

第一次 AI 的最小步驟、獨立 Compose、API及具體授權在 [LIVE_TEST_PLAN](AUTO002_LIVE_TEST_PLAN.md)。目前尚缺：本人獨立限額同意、受控 org/project／Key／模型權限證據、計數端點零費用證據、核准完整上界及批准啟用隔離單次環境。**不需要先公開 Privacy Callback 或重新做 OAuth。**
第一次真實 Threads 貼文：需另准現有帳號 Token 唯讀驗證、指定單篇不可變 Revision與文字、現有 Publisher的單次發布及官方讀回。AI許可不授予貼文權限。公開環境升級須另准備份、停機／升級／復原計畫；本次未升級。
持續自動生成及發文的舊 execution release 仍鎖定，單次 AI 許可不會解鎖；尚需獨立持續支出與發布政策、真實品質及計費驗證、正式部署審查。Privacy 未驗證不作為阻擋本機 AI 試驗的藉口，也不假稱正式 Callback 已驗證。

## 成本與界線

- 真實模型呼叫 **0次**；實際模型 API 費用 **USD 0**。
- 真實 Threads 發布 **0次**；沒有讀取或變更原生產憑證。
- Mock bytes／usage-shaped tokens／費用為測試輸入及模擬帳務；報告沒有把它們當真實 Token 或 invoice。
- 每個案例使用不同 synthetic usage，沒有可比較的真實模型品質／成本平均值；完整逐次數據在 Task receipts與attempt API，不虛構總帳單。
- 新增依賴／付費服務／常駐服務 **0**；只有暫時測試容器與本機合成 DB。
- Codex 本工作單 Token 使用量工具沒有提供分單統計，未估算。

風險：語意審查具機率性；保守逐句事實引用降低但不能消除漏判，Owner資料本身未外部查證。本地預算無法保證外部供應商絕對不超收。無新自動對帳重送機制；未知結果故意凍結等待查證。
完成後停止，等待本人另外批准真人測試與部署；不宣稱可正式營運。
