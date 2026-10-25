# MOS-P0.5-001 實作紀錄

日期：2026-10-25 Asia/Taipei。來源：`codex/marketing-ai-os-p0-hardening` / `0aed3c1229ac0c2d30a6e908f648ac9e96b3d852`。來源 SHA 與乾淨工作目錄核對後建立 `codex/marketing-ai-os-p0-5-readiness`；未重置 P0、未修改 main/develop/來源分支。無 P1 功能、付費模型或真實社群操作。

| 工作 | 最小實作與證據 |
|---|---|
| A CI | 既有 SQLite/PostgreSQL jobs 增加 compileall、mypy、commit diff whitespace 檢查；PostgreSQL job 繼續以 mos_app 驗證強制 RLS，新增合成備份還原演練及 artifact。來源 commit 的遠端 CI 已確認成功；本分支 CI 以 P05_TEST_EVIDENCE 的實際結果為準。 |
| B 身分／濫用 | 保留 hash/expiry/revocation/role AND scope；新 credential environment 限定，legacy/test key 不可跨進 production。共享 PostgreSQL/SQLite atomic rate limits，非 process-local counter；login/admin 每 peer 每 60 秒 10 次、其他 mutation 120 次。逾 24 小時未使用 counter 清理。 |
| C 備份 | pg_backup.sh / pg_restore.sh 僅允許指定 synthetic DB prefix、0600/0700、拒絕覆寫及部分檔案清理；backup_drill.py 在專用容器實跑九表 checksum/row-count 還原，詳見 P05_BACKUP_RESTORE。 |
| D 帳務 | 0003 增加 immutable rate_versions、reserve 時 snapshot、immutable snapshot DB trigger、receipt_status/source 及 ledger rate_version。既有金額仍 integer micro-USD。UNVERIFIED 是預設；無 API 能把 worker 自報收據升為 VERIFIED。 |
| E 排程 | app.scheduler 單一 tenant-bound worker loop、HTTP timeout、SIGTERM/SIGINT 與 restart policy。重用 /maintenance/recover 的安全冪等流程；單元測試及實際程序 restart smoke 通過。 |
| F 部署 | /health liveness、/ready schema/card/DB readiness；allowlist 結構化事件、handler filter 遮罩 message/exception；HTTP body 15s/64KiB、DB connect 5s/statement 10s/lock 5s、Provider 60s transport timeout。production 拒絕不安全 admin default、SQLite、HTTP 公開 URL、wildcard proxy、model/live flag。 |

## 操作與相容性

更新前先依 P0_DATABASE_MIGRATION_PLAN 備份。僅受控開發資料庫可執行 `.venv\Scripts\alembic upgrade head`，或 Compose migrate；0003 為 additive schema upgrade，不替舊收據杜撰 request-time rate。舊 credentials 標為 legacy，不可認證，管理員需重新核身發行正確環境憑證。舊 RESERVED tasks 沒有 request snapshot，禁止以新費率推定為歷史快照；新模型執行會拒絕缺失／不同版本，未知結果須人工對帳。

開發啟動仍可用 README 的 SQLite 或 loopback Docker。關閉真實模型預設不變。production 明確設定 MOS_ENV=production、MOS_PUBLIC_URL=https://實際網域、MOS_TRUSTED_PROXIES=明確代理 CIDR 與高強度專用 admin secret；Uvicorn 關閉自動 proxy-header 信任。middleware 只接受直接 TLS 或可信代理且 x-forwarded-proto=https。設定驗證不代表實際 TLS、proxy topology 與公開環境已安全驗證。

一個 recovery service 對應一個 tenant worker，先由 admin 發行 worker key，安全設定 MOS_WORKER_TOKEN 後：

```text
docker compose --profile recovery up --build -d recovery
```

預設 60 秒巡檢，環境可設 10–3600 秒。production 請另設 MOS_RECOVERY_API_URL 經安全代理，不繞過 HTTPS boundary。401/expired key 會紀錄 scheduler.failed，需更新／撤銷 key；不會偷偷換成 admin。不要把 worker token 放進 Git 或命令回顯。

## 依賴更新流程

runtime/dev 直接依賴 exact pin，constraints.txt 固定 resolver 的 transitive versions（不強迫安裝無關平台套件）；Python/PostgreSQL image 固定已測 digest。mypy 只在 dev/test image。更新在獨立分支：先查來源／license／release notes → 更新需要的 pin/constraints/digest → Windows/乾淨 Linux CI、RLS、備份與型別回歸 → pip-audit → 審核後合併。沒有自動升級到未測 latest。尚未採用全 wheel hash-lock/OS image CVE scan，保留 Production Gate。

收尾 commit 包含本紀錄與所有本機證據。遠端 CI 需要候選 commit 推送才能執行；不在取得成功前宣稱 P0.5 PASS。最終 SHA 與遠端結果見最後交付和 P05_TEST_EVIDENCE。
