# MOS-P0-009 最終驗收

日期：2026-10-25（Asia/Taipei）。結論：**P0 PASS，僅指本工單要求的離線開發／安全收尾範圍**。商用部署、實際 AI 帳單與真實平台整合尚未驗證，不代表商用就緒，不授權開始 P1。

分支：`codex/marketing-ai-os-p0-hardening`；起點 SHA：`53ef77487e18d512d9349fc005c03f3b2c5d9dbf`。既有修改全部保留，新增修改只有 P0 狀態競態修正、驗收回歸測試與交付文件。main 未修改。

最終 commit SHA 以本檔所在提交及最終交付訊息為準：`git log -1 --format=%H -- docs/P0_FINAL_ACCEPTANCE.md`。推送結果以實際 Git 回應／最終交付為準，本文件不預先宣稱已推送。REMOTE_CI_NOT_VERIFIED。

## A：逐項對照原始八項要求

| 原始要求 | 核對的程式／設定 | 測試／證據 | 結論 |
|---|---|---|---|
| 1 認證、RBAC、scoped worker | `app/security.py`、`app/main.py` login/credentials/settle | `tests/test_api.py::test_passwordless_replay_expiry_and_scope`、`tests/test_acceptance.py::test_registry_and_illegal_transitions` | PASS；管理員人工核身及交付 challenge，並非公開自助寄信服務 |
| 2 多租戶、migration、immutable audit | `app/database.py`、`app/models.py`、`migrations/versions/0001_schema.py`、`0002_defense.py` | `test_db_isolation_and_immutable_audit`、`test_postgres_all_tables_raw_isolation`；`p0-009/deployment.txt` | PASS；PostgreSQL 七表 FORCE RLS、runtime 非 owner／非 superuser；SQLite 僅 ORM 防護 |
| 3 精確帳本、預留／結算／釋放、超時、kill switch | `app/main.py` reserve/claim/settle_receipt/release/recover、整數 micro-USD models | `test_concurrent_reserve_settle_publication`、`test_concurrent_budget_competition_and_release`、`test_timeout_kill_switch_and_receipt_overrun`、`test_duplicate_receipt_rolls_back_whole_transaction` | PASS；實際帳單僅有合成收據測試，沒有聲稱已付費對帳 |
| 4 模型介面、預設禁用、usage metadata | `app/providers.py` LLMProvider/AnthropicProvider、`app/main.py` execute | `test_provider_http_contract_and_explicit_opt_in`、`test_execute_receipt_metadata_and_idempotency`、token/error regressions | PASS；HTTP mock，實際 paid API 未呼叫 |
| 5 四平台保守介面 | `app/adapters.py`、publication-request | 四組 `test_platform_fails_closed`；重複 publication key 測試 | PASS；只有 MANUAL_REQUIRED，無實際發布能力 |
| 6 模型費率與來源、有效日、cache rate | `config/models.json`、`app/providers.py::usage_cost` | `test_money_and_validation`、provider contract；`docs/DEPENDENCIES.md` | PASS：來源／日期／rate config 已核對；未在本次重新查詢供應商費率或驗證帳單，禁止視為即時報價 |
| 7 CI、漏洞掃描、安全與並行測試 | `.github/workflows/ci.yml`、`tests/test_api.py`、`tests/test_acceptance.py` | 本次 raw reports：`docs/p0-009/` | PASS 本機；REMOTE_CI_NOT_VERIFIED |
| 8 本機與 Docker PostgreSQL 操作 | README、Dockerfile、compose.yaml、scripts/init-db.sh、alembic.ini | 全新 mos-p0-009 資料卷、自動 migration、runtime image build／health | PASS；不觸碰既有資料卷 |

Agent Registry 另行核對 `app/registry.py`：A01–A24 唯一且完整，狀態均為 REGISTERED_NOT_EXECUTING。未知 agent 的 task create 回傳 422。沒有將 registry 當成已運行的 agent。

## B：本次實跑結果

| 檢查 | 結果 | 原始證據 |
|---|---|---|
| SQLite | 24 passed, 1 skipped, 1 deselected；5.54s | `p0-009/sqlite.txt` |
| PostgreSQL 16，受限 runtime role | 25 passed, 1 deselected；5.06s | `p0-009/postgres-final.txt` |
| 首輪全新 PostgreSQL 資料卷初始化 | 建庫、init script、0001→0002 與首輪 suite 通過 | `p0-009/postgres.txt` |
| 靜態程式檢查 | Python AST、compileall、model JSON、CI YAML 結構、Compose config、git diff --check 通過 | `p0-009/static.txt`、提交前 staged check |
| 型別檢查 | NOT_CONFIGURED；專案沒有 mypy／pyright 設定及依賴，未引入新工具 | `p0-009/static.txt` |
| 依賴漏洞 | requirements-dev（含 runtime）掃描 exit 0，零已知漏洞 | `p0-009/dependency-audit.json` |
| 敏感資料／提交範圍 | 見提交前 scan 與 staged manifest；.env.example 僅 placeholder | `p0-009/precommit-security.txt`、`p0-009/precommit-status.txt` |

SQLite 的單一 skip：`test_postgres_all_tables_raw_isolation`，因 SQLite 不支援 PostgreSQL RLS。此跳過合理，且同一測試在 PostgreSQL 執行通過。兩套 suite 都 deselect `live`，符合禁止付費 Live AI API 原則。HTTPX TestClient 有一項上游 deprecation warning，尚不影響本次測試。

## 特別安全／整合驗收

- Tenant A 無法讀寫 Tenant B：API negative、ORM write guard、PostgreSQL 每張表 raw SELECT/UPDATE/INSERT、無 tenant context default deny，全部通過。
- 一般使用者不能批准發布：manager、reviewer、worker 均 403；owner 也必須在 PENDING_APPROVAL 才能批准。
- Token 超限／預留金額不足：`test_token_or_money_limit_prevents_generation` 回傳 402，generation 未呼叫、spent=0。DRAFT 是不花 token 的草稿登記，仍可建立；本系統不提供按月 token 數量配額，不能把美元預算說成月 token quota。
- API 失敗不重扣：模擬 exception 含假 API key，502 後重試 409，只有一次 generate、零 SETTLE、spent=0、款項保留待對帳。
- 重複 webhook：本系統根本沒有 webhook 接收器，重複 `/webhooks/threads` 均 404，無新增 publication；已批准的 publication-request 重試返回同一 ID。這證明目前 fail-closed，不等於已實作簽章驗證／事件去重。
- 並行任務總預算：八路 competing reserve 只允許預算容納的任務；duplicate reserve/settle/release/publication 均未重記帳。
- API key log：caplog／stdout／stderr／錯誤 response／audit 中均不出現測試 bearer、admin、provider secret；本測試不涵蓋外部反向代理及使用者自建 logging handler。
- 非法狀態轉換：DRAFT claim/settle/approve/release、結算後 claim/release、未批准 publication 均拒絕。
- 本次修正：count_tokens 後重新取得 tenant lock 並重讀 task；任務已轉狀態或已過期時拒絕 generation。三組回歸測試覆蓋待對帳、已結算、過期情況，避免以舊狀態送出模型請求。

## C–E：部署、資料與交付

migration 版本 0002，七張資料表 FORCE RLS，mos_app superuser=false、bypassrls=false，health 回傳 model/publishing=false，證據在 `p0-009/deployment.txt`。

舊資料庫只交付 `P0_DATABASE_MIGRATION_PLAN.md` 規劃，未轉換或還原任何既有資料。另以 tmp_path 合成 SQLite 舊表，證明 baseline 明確拒絕且原資料保持原值。

成本：`P0_COST_REPORT.md`；限制：`P0_KNOWN_LIMITATIONS.md`；P1 準備：`P1_READINESS.md`。本次 paid AI API：0 calls / USD 0。本次 agent token 使用量沒有可用的 per-task 計量工具，記為 NOT_AVAILABLE，沒有猜測數字。

本地離線收尾通過後才允許提交；正式商用 readiness 仍不足。不建議開始 P1 功能，先確認已列出的必要基礎設施與證據門檻。
