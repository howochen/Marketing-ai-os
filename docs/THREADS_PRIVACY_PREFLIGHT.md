# Threads 回呼部署前驗證與正式部署計畫

日期：2026-10-27。程式基準：`abfc053df6a3688e9e5de81c838995ca0b472f9b`。

**部署 NO-GO。使用者未授權修改運行中 DB、公開新回呼；本次沒有部署。**
隔離驗證成功不代表現行 Meta Threads Callback 相容，也不是刪除合規或正式營運驗收。

## 實際還原、升級及資料相容性

證據：`threads-privacy/preflight/restore-upgrade.json`、`postgres-regression.txt`、`windows-security.txt`。

本次 PostgreSQL 回呼／發布安全契約／社群 UI／內容工作台回歸 **103 passed**；Windows SQLite 回呼安全＋安裝器順序＋原生 DPAPI／Tk **74 passed**；mypy **30 個來源檔通過**。這是有針對性的本次重跑，不冒稱又執行了全套；基準提交的全套 413 SQLite／409 PostgreSQL 與 CI 成功證據另見原驗收文件。新測試合計將回呼案例從 27 增至 29，沒有修改正式執行程式或 migration。

- 使用既有 0012 原環境備份，重新校驗 SHA-256，不以先前 pg_restore --list 成功代替本次實際還原。
- 每次產生唯一 `mos-privacy-preflight-*` PostgreSQL 容器。`--network none`、無 port binding、DB 與備份只放 tmpfs。測試映像加入該容器網路命名空間，只能經 localhost 存取該獨立 PostgreSQL，無外部網路。
- 備份以 stdin 寫入隔離 0600 檔，沒有修改原備份 ACL。最初 docker cp 的檔案權限檢查失敗即中止並清理；改用隔離串流後完整重跑。
- 備份還原至 `private_upgrade`，確認 schema 0012，實際以非 superuser 的 mos_migrator 執行 0013。
- 21 張舊業務表逐列序列化原欄位、排序後雜湊比對一致。包含內容工作台、Revision、批准、帳務、Threads 連接、OAuth state 與手機初始化紀錄；新增兩欄為 NULL、新收據及處理表為空。未猜測舊 App 綁定。
- 還原副本使用 mos_app 啟動現有 FastAPI，檢查 `/app`、`/ready`、未登入內容 API 及缺 state 的 OAuth 拒絕；依 Tenant scope 讀取 Task／Revision／Approval／Publication／ContentPlan／ThreadsConnection／OAuthState ORM。沒有對真實帳號發出 OAuth 或 Provider HTTP。
- 另建 `private_rollback` 再還原同一備份，版本回到 0012，包含 alembic_version 的舊表指紋全部一致。不是對已升級 DB 強行 downgrade。
- Windows 既有 DPAPI Vault 在主機記憶體解密成功，既有 Token 金鑰可往返加解密；原 Vault 位元組保持一致。備份沒有儲存 Token 樣本，故真實 Token 密文解密欄位為 `NOT_EXERCISED_NO_STORED_TOKEN`；另有合成 OAuth／加密／DPAPI 回歸，不把它說成真實 Token 驗證。
- 真實備份內資料未用於可修改的回歸測試。回歸只在另一個空白 `synthetic_regression` DB 使用合成資料執行；原 DB 前後全表指紋與原 Vault／兩個未提交 Cmd 檔位元組相同。
- 實驗結束移除本次唯一且有標籤的 tmpfs 容器，無還原副本、原憑證或私人 DB 留在測試 volume。沒有刪除既有 Docker Volume。

安全測試包括錯 Secret／App／時戳、重放及並行重複通知、跨 Tenant／其他 App／其他帳號、舊事件不覆蓋新授權、未綁定舊帳號待審、故障恢復、RLS、在途發布結果保留及禁止假報 COMPLETED。另新增兩案例明確核對合法刪除及不存在帳號通知前後：Task、Revision、Approval、Score、Ledger、ContentPlan 不變，舊 Audit 不變，另一帳號 Token 保留，沒有發出 publish 呼叫。

## 官方現行規格：NOT_VERIFIED

以下官方網址本次重新查核仍為 429／不可取得，不以搜尋摘要、第三方網站、封存 Facebook SDK 或合成表單取代現行 Threads 規格。

| 官方資料 | 查核結果 |
|---|---|
| https://developers.facebook.com/docs/threads/get-started/create-an-app/ | 429，NOT_VERIFIED |
| https://developers.facebook.com/docs/threads/get-started/ | 429，NOT_VERIFIED |
| https://developers.facebook.com/docs/threads/overview/ | 429，NOT_VERIFIED |
| https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/#deauth-callback | 429，NOT_VERIFIED |
| https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback/ | 429，NOT_VERIFIED |
| https://developers.facebook.com/docs/apps/delete-data/ | 無法擷取，NOT_VERIFIED |

待確認的具體項目：Threads Uninstall／Data Deletion 的 HTTP method、Content-Type、signed_request 欄位、base64url 與演算法、實際簽章 Secret 所屬 App、user_id 命名空間、issued_at 是否存在及時間語意、回應 status/body／url／confirmation_code、重送與逾時條件、刪除完成及保留證據要求。**全部現行相容性 NOT_VERIFIED。**

目前程式實作的 HMAC-SHA256／form／issued_at／24h 政策只是待驗證契約，不能推定 Meta 一定送相同內容。未取得可引用的當日官方規格前，不公開、不降低簽章檢查、不填無效網址來通過表單。官方文件取得後，先比對並視需要更正程式、重跑隔離測試；實際 Meta 送達仍需另行授權並由本人進行撤銷／刪除測試。

## 是否真正需要 Migration 0013

**目前實作需要；本次只在隔離副本實施。** 0012 的 threads_connections 沒有 App 身分及簽章帳號查找綁定；既有 audit_logs 只有 actor/action/resource/time，無法提供原子冪等收據、確認碼、不可改寫目標清單及每 Tenant 處理狀態。直接挪用 Audit 或連接狀態當收據，會失去唯一約束、恢復依據與對應 RLS。

0013 最小差異為兩個 nullable 欄位、一個 connection 查找索引、兩個收據／處理表及其唯一鍵、外鍵、RLS／不可改寫 trigger。沒有回填、改寫或刪除舊資料，也未另建 Token Vault、內容或發布系統。現行程式 ORM 與 readiness 已要求 0013，不能把此版程式直接部署在 0012。若官方規格導致設計需要改動，應在部署前調整尚未上線的設計並重新驗證，不提前對原庫遷移。

## 原環境預期差異

| 項目 | 現在（未變動） | 未來另獲批准的部署後預期 |
|---|---|---|
| DB | schema 0012，原 mos-threads-local_pgdata | 0013；原欄位值保留、增量表空白 |
| API | 原映像，兩個 privacy URL 不存在 | 更新映像、readiness 0013；公開簽章接收端及安全狀態頁 |
| OAuth | 原 Callback／憑證／加密金鑰 | 路徑與金鑰保留；新授權紀錄綁定 App |
| 舊帳號 | 原資料保留 | 不自動回填 App；需 Owner 官方檢查連線後綁定，未驗證前不得發布／刷新 |
| 內容工作台 | 現有 Task／Revision／Approval／Plan | 功能保留，回呼不刪除人工作品 |
| UI／安裝器 | 原運行版本 | 列出三網址；Meta 保存聲明不代表官方驗證 |
| 發文／AI／手機秘密通道 | 不啟用 | 仍不啟用；不開新的 Worker |

## 備份位置與回復方案

既有備份（私人路徑，不提交 dump）：
`D:\AI\Marketing-ai-os\.threads-local\backups\privacy-pre0013-3c4b5773ebe14d47bdb5fb66236ecee2.dump`

SHA-256：`44c244048da2500f1d36542d716eea1dd3c319f2b70c16a43a54bd39675f2ed7`。
Windows 檔案 ACL 實查只有目前使用者與 SYSTEM；沿用受限父目錄 ACL。備份不是加密檔，含敏感 DB 資料，不得上傳 Git、CI artifact、聊天或一般共享目錄；後續若離機保存應使用受控加密儲存。本次沒有改 ACL、沒有記錄 Secret。

原 API 映像 ID：`sha256:e6773295314bb877d87cb570f999ec0b2348d50b828cc4765fea321f5fffa442`。
原 DB volume：`mos-threads-local_pgdata`。原來源 SHA：`05d0858b04aeea9f9cb7c71d2da98bd8954c1e4e`；兩個既有未提交 Cmd 變更需另外保留，不 reset checkout。

回復應使用原映像與已驗證的 **0012 備份還原到新獨立 DB／volume**，檢查指紋、角色／權限及 schema，再經批准切換連線。不得 pg_restore 覆蓋唯一原 volume、不得 alembic downgrade 0013（此 migration 明確拒絕），不得把新版 ORM 接到 0012。DPAPI Vault 與 Token 金鑰保持同一 Windows 使用者與原檔案，不產生新金鑰替代。

恢復到備份時間點會遺失之後寫入；部署前必須停止寫入並重做新備份。若已接收回呼或有新內容，先保留 0013 DB／收據及差異以人工核對，不盲目用舊備份抹掉撤銷／刪除證據或復活已撤銷 Token。本次隔離還原秒數只是這份小備份的實測，不是營運 RTO／RPO 保證。

## 正式部署計畫（本次不執行）

1. 取得當日官方規格及 Threads 專用 App 身分／簽章要求，完成契約差異審查；必要時修正測試與程式。若仍不可取得，維持 NO-GO。
2. 確認資料刪除的保留範圍、處理負責人與追蹤時限。現在只撤銷憑證及清除可變帳號欄位，REVIEW_REQUIRED 絕不是完整刪除或 Meta 合規通過。
3. 提交精確待部署 SHA／映像、離線測試與 CI 證據，由使用者另外批准「資料庫升級＋API 更新＋公開兩回呼」。現有拒絕部署的指示持續有效。
4. 先建置並保存新舊映像。安排短暫維護窗、暫停內容寫入及背景寫入、確認沒有在途發布。保持 ngrok 原網址，不更動 OAuth／DPAPI。重新取得一致性備份與完整性／ACL 校驗，記錄停止寫入時間。
5. 在維護窗內使用專屬 migration role 套用 0013；核對版本、舊欄位指紋、RLS 與空新表，再更新 API。任何失敗都不公開新端點，按上述新庫還原方案回復。
6. 先本機 health／ready、工作台讀取／登入、OAuth 狀態拒絕及未簽章回呼負面檢查；確認 AI／發文／手機通道關閉。成功才依批准公開兩新回呼；簽章不明一律拒絕，不使用真實資料做刪除演練。
7. 本人在 Meta 保存三網址，使用本人測試帳號另行核准官方回呼實測，核對原始請求的安全解析、App／帳號、確認碼及後台記錄；不記錄完整表單或 Token。分別報告 PUBLIC_ENDPOINT_READY 與 META_CALLBACK_VERIFIED，不能互相代替。
8. 工作台資料、租戶隔離及 OAuth 回歸完成，才解除維護。未知結果保留待對帳，不自動重新授權、發布或刪除外部貼文。

**停機：本次沒有停機。正式部署建議短暫維護窗**，因 0013 的 ALTER TABLE／policy／trigger 需要鎖，且新舊 ORM 不宜混跑。沒有宣稱零停機；需以部署前鎖／資料量檢查及演練決定時間。允許的恢復時間也需由使用者另行接受。

## GO／NO-GO

- 隔離還原、升級與合成安全回歸：依附檔實測結果；可以繼續離線規格核對。
- 正式 DB 升級／公開端點：**NO-GO**，官方契約 NOT_VERIFIED、未獲部署批准、完整刪除處理範圍未完成。
- Meta 真實送達、OAuth 真實帳號驗證：**NOT_VERIFIED**。
- 真實發文、付費 AI、手機秘密管理通道、正式營運：**NO-GO**。

本次驗證完成後停止，不執行安裝器、Docker compose up 原專案、Meta 授權撤銷或任何公開啟用操作。
