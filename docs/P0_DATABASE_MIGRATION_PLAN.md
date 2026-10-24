# 舊資料庫遷移、備份與回滾規劃 — MOS-P0-009

**本文件僅為操作規劃，未對既有資料庫執行任何備份、轉換、刪除、還原或切換。** 目前 migration 僅支援全新 schema；0001 偵測 tenants 已存在便拒絕。禁止用 alembic stamp 把舊 float schema 假裝成新 schema，禁止 compose down -v、覆寫原 .db／原 volume 或在 main 直接更動。

## 1. 盤點與凍結

先記錄來源 schema／revision、應用 commit、DB／driver 版本、tenant/task/audit/cost-event 數量及每租戶 spent/reserved/budget 的原始值。確認是否有 RUNNING／未知已計費請求；先取得供應商實際收據，不將模擬帳本當成真實支出。安排維護窗停止所有寫入者與背景排程；資料 owner 批准後才操作。所有檔案加密、限制 ACL、記錄 checksum、時間、操作者及保存期限，密鑰不放進命令列或報告。

## 2. 備份計畫（尚未執行）

SQLite：應用及 writer 停止後，使用 Python stdlib sqlite3 的 Connection.backup API 從唯讀來源連線備份到全新檔名；備份檔已存在就拒絕，避免覆蓋。不要在活躍 WAL DB 只複製主 .db 檔。對副本執行 PRAGMA integrity_check，核對資料數量、每租戶餘額與 audit；保留原來源不變。

PostgreSQL：由經授權可讀全部 tenant 的備份身分做一致性 pg_dump custom-format；runtime mos_app 受 RLS 限制，不可當成全租戶備份身分。用受限的 pg_service.conf／pgpass 或 secret manager，避免 URL 密碼出現在 process list。示意命令（須由 operator 設定 service 與全新輸出路徑，**本工單不執行**）：

```text
pg_dump --dbname="service=mos_backup" --format=custom --file="<new-encrypted-backup-location>/before-p0.dump"
pg_restore --list "<new-encrypted-backup-location>/before-p0.dump"
```

另外備份所需 role/grant 定義與獨立管理的 secrets。pg_restore --list 只驗證目錄可讀，不能取代還原演練；需在全新隔離資料庫還原副本，驗證約束、row counts、每租戶帳務總和與資料抽查。不得把驗證副本連到真實社群或 AI API。

## 3. 平行轉換設計與審核

- 新建不同 DB／volume，先執行 alembic upgrade head 至 0002，不動原 DB。
- 另行設計一次性、有 dry-run 報告的 importer；目前尚未實作／授權。確認 row mapping、錯誤處理及交易範圍後才可以開發。
- 舊 float 無法完全還原原始十進位意圖。以 Decimal 表示原始匯出值，列出轉 micro-USD 的每筆差額；由財務先批准 rounding 與 reconciliation 規則，再固定測試。不得靜默捨入或直接 binary-float × 1e6 後截斷。
- 舊 tenant API key 不自動變 owner／worker。舊 credential 失效，人工重新核身並 issue／安全交付新 credential。
- 舊 SETTLE_SIMULATED 仍標記模擬；不可導入成真實 provider receipt 或假造 message ID。RUNNING／reserved 任務逐筆 reconcile，不盲目 release。
- 保留舊 audit 不可變原件／checksum；任何遷移紀錄附原識別、migration batch、actor、來源證據，不能刪改舊事件。新表觸發器不能為方便匯入而關閉；由專用 migration 身分在隔離目標按核准流程插入。
- 核對 composite tenant FKs、RLS、角色與七表 policy、每租戶預算及帳務守恆、重試與 receipt uniqueness；同一批不能重複匯入。

## 4. 切換與回滾計畫

只有 dry-run、備份還原演練、帳務差額核准與完整 regression 通過後，才由 operator 批准切換 DATABASE_URL。保持舊 DB 唯讀、保存舊應用 commit／schema 相容性。切換初期關閉 model/publishing flag，以受控資料驗證 health／登入／tenant isolation。

回滾不是 alembic downgrade（目前故意拒絕）。先停 writer，保存失敗目標快照、audit 與切換後新增資料清單；確認沒有遺漏已計費請求。若切換後已接受新資料，必須先設計對帳／回補，不可直接丟失這些資料。只有確認 rollback 不會遺失新資料與帳單後，才切回保留的舊應用＋舊 DB，或將驗證備份還原至另一個全新 DB，再切換；禁止 restore 覆寫唯一來源。RPO/RTO 需依還原演練測量，不提供未測量的承諾。

## 本工單已驗證的安全邊界

`tests/test_acceptance.py::test_unmanaged_legacy_database_is_not_overwritten` 只建立 tmp_path 合成舊 SQLite 表，驗證 upgrade 拒絕且原 row／值不變。這不是正式舊資料轉換或還原演練。新 PostgreSQL migration 已在本工單獨立全新 volume 通過，見 docs/p0-009/postgres.txt。
