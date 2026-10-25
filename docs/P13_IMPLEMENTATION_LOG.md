# MOS-P1.3-001 實作紀錄

驗證日期：2026-10-26（Asia/Taipei）。來源分支 `codex/marketing-ai-os-p1-2-provider-readiness`，精確 SHA `eb15715244009f1386176d6055224b1a8a52d083`；開始時工作目錄乾淨，從該 SHA 建立 `codex/marketing-ai-os-p1-3-durable-gate`。沒有修改 main、develop 或前階段分支。

| 新增／修改 | 用途 |
|---|---|
| `app/durable_gate.py` | Synthetic Batch／Attempt API、原子 admission、結果落盤、Recovery、測試收據匯入 |
| `app/batch_mock.py` | 固定 MockTransport 場景，內建無帳戶的 synthetic credential，不接受 client transport／API Key |
| `app/models.py`, `0007_durable_gate.py` | 三張新表、租戶 FK／unique／CHECK、RLS、授權與請求快照保護、狀態轉換、不可刪歷史 |
| `app/main.py` | 抽出原 reserve_funds，claim／settle 支援同交易；舊 API 行為保留，batch Task 防旁路；既有 Recovery 接入 |
| `app/openai_provider.py` | synthetic-only 模式拒絕環境 key，生成 client request ID 可在 dispatch 前持久化；Live transport 仍拒絕 |
| `app/database.py` | 新三表加入 ORM tenant scope，Evidence 加入 append-only flush guard |
| 既有 A09／rehearsal | 拒絕繞過 coordinator 執行已綁 Batch 的 Task；其餘流程保留 |
| backup／CI／mypy | 新15表備份指紋、專屬 p13 合成專案、schema head0007、17模組型別檢查 |

Batch 的 reserved／estimated_spent 是原 Tenant Ledger 的同交易批次投影，不是另一個資金帳本。沒有新支付系統、queue broker 或常駐 Agent。每次 admission 將原 Task 預留、RESERVE event、Attempt、Batch 名額／預留與 Audit 一次提交；結算同樣一次提交，不留下半套計數。

0007 為新增三張表，不改寫舊 Task、價格或 Ledger。migration 自含固定 schema／guard，不從可變 runtime models 建表。舊資料升級回歸仍通過；downgrade 不刪歷史，需停止寫入並依既有計畫還原驗證備份到獨立 DB。

主要修正過程：初次並行測試的 fixture 將 request cap 設為2000、batch cap1600，API 正確拒絕；修正測試設定而非放寬驗證。另補齊遲到結果與人工匯入競爭的保存／成本差額處理。既有184項 SQLite 測試先驗證通過，再加入28項 Durable Gate 測試。

重現：`pytest -q tests/test_durable_gate.py`，完整 `pytest -q`、`mypy`、`python -m compileall -q app tests migrations scripts`、`pip-audit -r requirements-dev.txt`。PostgreSQL 使用僅供測試的 compose 密碼，`docker compose -p mos-p13-test --profile test run --build --rm tests`。所有產物在 `docs/p13/`，不含 dump、真實憑證或客戶資料。

備份：僅對本次新建合成卷設定 `MOS_DRILL_PROJECT=mos-p13-test` 執行 `python scripts/backup_drill.py`，核對 Docker labels、15表指紋與獨立還原目標。未觸碰既有資料卷；腳本拒絕覆寫還原目標。實測時間與權限結果見 `p13/backup-restore.json`。

實作提交 `e0cfbe5b5bcfcf5de5a22a0a86de4981d008a08f` 已推送；[遠端CI 40211352227](https://github.com/howochen/Marketing-ai-os/actions/runs/40211352227) SQLite212／PG213／mypy17／漏洞掃描／備份還原皆成功。後續僅文件與證據提交，最後交付仍核對其exact SHA CI。專屬合成API／DB容器已停止，volume／備份保留，未停止其他專案。
