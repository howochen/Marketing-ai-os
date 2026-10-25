# P0.5 備份與還原演練

本機 2026-10-25，`scripts/backup_drill.py` 已實跑 PASS。只操作新建立的 mos-p05-test 專案容器及該容器內 mos_p05_dr_source_001 / mos_p05_dr_restore_001；來源 mos 也只有本工單 pytest 合成資料。沒有接觸原 P0／客戶 volume。

腳本：`scripts/pg_backup.sh` 使用 pg_dump custom format；`scripts/pg_restore.sh` 使用 createdb + pg_restore --single-transaction --exit-on-error --no-owner。前者只允許 mos_p05_dr_source_*、固定 private directory 下新 .dump；後者只允許 mos_p05_dr_restore_*，目標存在即失敗。不使用 DROP、--clean 或 restore 覆蓋現存 DB。輸出用 temporary file、trap 清理、atomic hard link，不覆蓋既有 archive；拒絕 directory traversal／備份目錄 symlink。

## 實測流程及結果

1. 專用 container/project label 核對，建立獨立 synthetic source，clone 此專案測試資料。
2. 對 tenants/tasks/credentials/login_challenges/cost_events/audit_logs/publications/rate_versions/rate_limits 九表保存 row-count 與排序後 row JSON checksum。
3. 備份約 **0.324 秒**；private archive 0600、directory 0700。備份含憑證 hash／任務資料，仍視為敏感資訊。
4. 故意 DELETE 合成 source credentials，確認 count=0。
5. 還原至另一個全新 DB，加九表檢查約 **2.528 秒**；counts/checksums 全相同，snapshot rows lost=0。
6. 四項 negative assertions：低權限 OS user 不可讀 archive、existing target restore 拒絕、non-drill source 拒絕、missing source 失敗且不留下成功 archive。

原始量測與 fingerprints：`p05/backup-restore.json`。CI PostgreSQL job 同樣實跑，artifact 僅上傳證據 JSON，不上傳 backup archive 或 credentials。

## 重現（僅全新測試專案）

```text
docker compose -p mos-p05-test --profile test run --build --rm tests
python scripts/backup_drill.py
```

需已設定 .env 的 development placeholder 替換值。再次執行同一 drill 會因既有 source/target/檔案而 fail-closed；不要為方便重跑刪除不明 volume。CI 每次全新 runner。若要重跑本機，先由 operator 確認純 synthetic 資料，另行規劃新名稱／全新環境；腳本不會自動 drop。

## RTO / RPO 邊界

2.528 秒是這個小型本機快照 restore+九表驗證時間，未包含事故偵測、網路、人工決策、環境重建與 DNS／應用切換。無業務 RTO/RPO 目標獲核准，不聲稱 SLA。

RPO 只證明沒有 backup 期間寫入的合成快照完整恢復；沒有 continuous backup/WAL archive/PITR，因此後續寫入仍會遺失，不能聲稱 RPO=0 的正式能力。尚缺加密 archive、離機／異地 retention、密鑰管理、production restore drill、負載規模測試、signed backup manifest。container root / Docker admin 可讀 archive；OS mode 不防禦管理員。演練資料保留於測試容器內，未提交 Git；.dump 已 ignore。
