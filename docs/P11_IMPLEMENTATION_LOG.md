# MOS-P1.1-001 實作紀錄

範圍：離線 Mock、合成資料與人工修訂。來源 `cc23f454e1414315714efc7b2695583619939f3f`，來源分支 `codex/marketing-ai-os-p1-agent-runtime`；開始時工作目錄乾淨，從該 SHA 建立 `codex/marketing-ai-os-p1-1-quality-evals`。未修改 main、develop 或來源分支。

沿用既有 A09、A21 QA、租戶鎖、身分驗證、整數 micro-USD Ledger、request rate snapshot、Kill Switch 與手動發布介面。沒有第二個 Runtime、付費評審、背景 Agent process 或新外部依賴。

| 變更 | 位置 |
|---|---|
| 六產業 × 10 固定案例、版本、預期結果及理由 | `agents/A09/evals/v1_1/cases.json` |
| 八項 0–5 rubric、來源與判分說明 | `agents/A09/evals/v1_1/rubric.json`, `app/quality.py` |
| 按需載入產業規則、專業宣稱及不可信輸入阻擋 | `skills/industries/`, `app/industry_rules.py`, `app/agent_runtime.py` |
| 不可覆寫 Revision、獨立 Approval／Human Score 事件 | `app/models.py`, `app/revisions.py`, `app/database.py` |
| 批准精確綁定、發布內容快照及 DB 防改寫 | `app/main.py`, `migrations/versions/0005_quality_revisions.py` |
| Byte／Mock unit／Provider token／費用分離 | `app/measurement.py`, `app/providers.py`, `app/agent_schemas.py` |
| 回歸、Docker、type、CI、備份涵蓋新表 | `tests/test_quality_revisions.py`, `Dockerfile`, `mypy.ini`, `.github/workflows/ci.yml`, `scripts/backup_drill.py` |

Schema 0004 → 0005 新增三張表及 nullable 指標／發布快照。SQLite 的 publication FK 使用 Alembic batch table copy，測試證明舊 publication／task 內容保留；PostgreSQL 使用 ALTER。沒有歷史資料重寫、虛構批准或 Token 換算。舊 Task／Publication 指標維持 NULL，必須重新取得指定版本批准才能建立新佇列；舊佇列維持 MANUAL_REQUIRED。既有未版本化手動內容的來源標示 LEGACY_UNVERIFIED，不能假稱 MOCK 或 HUMAN。

升級前沿用 P0 備份與回滾計畫，在副本驗證 `alembic upgrade head`。禁止 destructive downgrade；需要回滾時停止寫入並還原已驗證備份到獨立資料庫，不以 downgrade 刪除歷史。新表納入 12 表備份指紋；本次演練見 `p11/backup-restore.json`，備份檔未進 Git。

開發時資料集補充產業情境曾覆蓋 missing-information／injection 負面欄位，測試如預期抓到 13 個失敗；修正 Fixtures 欄位保留，沒有放寬 QA。最終完整結果以 `p11/sqlite.txt`、`p11/postgres.txt` 為準。保留 Starlette 對 HTTPX 的棄用警告，沒有為消除警告更換依賴。

重現方式：安裝既有 `requirements-dev.txt`，執行 `pytest -q`、`mypy`、`python -m compileall -q app tests migrations scripts`、`pip-audit -r requirements-dev.txt`。PostgreSQL：設定僅供測試的 compose 密碼後 `docker compose -p mos-p11-test --profile test run --build --rm tests`；備份演練需在該獨立測試專案設定 `MOS_DRILL_PROJECT=mos-p11-test` 執行 `python scripts/backup_drill.py`。腳本只接受 p05/p11 兩個合成測試專案，且以 Docker label 再核對；重跑演練應使用新測試卷，禁止覆蓋既有還原目標。

部署與 CI 狀態以 [最終驗收](P11_FINAL_ACCEPTANCE.md) 為準。

實作提交 `aea0fc09a49a387c64d2ce1ccd011cbe5de996a0` 已推送，遠端 CI [40156837776](https://github.com/howochen/Marketing-ai-os/actions/runs/40156837776) success；測試與 backup job 實際通過，原始摘要見 `p11/remote-ci-summary.txt`。後續提交僅補入此證據與驗收狀態，最終交付仍核對最後 SHA 的 CI。
