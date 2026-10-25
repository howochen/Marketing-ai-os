# P1.1 Revision 安全設計

DraftRevision 保存 tenant/task/revision/original/parent ID、MOCK／HUMAN 來源、前後文字與結構化 draft、原因、品牌資料 SHA-256 版本、Prompt 版本、QA／rubric 快照、建立者與時間。歷史未版本化內容另標 LEGACY_UNVERIFIED，不推測來源。審核者及批准狀態來自獨立不可覆寫 RevisionApproval 事件；API 合併顯示。人工分數為獨立 append-only RevisionScore，不能修改 draft、預算或批准。

| 操作 | API／權限 |
|---|---|
| 原稿、最新待審與完整歷史／diff | GET `/tasks/{id}/revisions`、`/{revision_id}`；同租戶 read |
| 人工修訂 | POST `/tasks/{id}/revisions`；owner／manager 的 tasks scope，parent 必須最新 |
| QA 重跑 | POST `/tasks/{id}/revisions/{rid}/qa`；同租戶 read，0 模型呼叫，不覆寫原 QA |
| 指定版本批准 | POST `/tasks/{id}/revisions/{rid}/approve`；owner + approve scope |
| 人工評分／讀取 | POST／GET `/tasks/{id}/revisions/{rid}/scores`；寫入限 owner／manager／reviewer，worker 禁止 |
| 手動發布佇列 | 既有 publication-request；owner／manager，綁定已批准且為最新的 revision_id 與文字快照 |

修訂與批准均先取得既有 tenant row lock。相同 idempotency key＋payload 重用同一版本；改變 payload 衝突；過期 parent 拒絕。新版本一律 PENDING_APPROVAL，清除 task 的 approved_revision_id／approved_by，保留舊批准事件；批准只允許最新版本，並重新跑當前 QA，任何硬性失敗均拒絕。並行修改／批准不會把原稿批准套用到新稿。

相容性：舊 `/tasks/{id}/approve` 無 body 呼叫只可解析唯一原始版本，仍在同一把鎖內記錄精確 Revision ID；一旦有人工修訂就要求 body `{"revision_id":"..."}`，不得以含糊的 task 批准新版本。新客戶端一律使用指定版本 API。舊 P1 已批准但無版本的資料，不以 migration 補造批准；須 owner 重新批准。

發布永遠 MANUAL_REQUIRED，不實作社群請求。新 Publication 有 tenant/task/revision composite FK、approved revision 的 content_snapshot。DB trigger 要求快照文字與批准版本一致，已綁定的 revision／文字不可更新。後續修訂不會改動已排入的舊版快照；同一 publication key 不可被重用來排入另一版本。歷史無 revision 的 publication 不補造內容，不能視為可自動執行。

三張新表都有 ORM 租戶限制、寫入租戶驗證與 append-only flush guard；SQLite UPDATE／DELETE trigger；PostgreSQL ENABLE/FORCE RLS + WITH CHECK policy，runtime role 非 owner／superuser，UPDATE／DELETE／TRUNCATE trigger。親版本與批准／評分 composite FK 防跨 task／tenant 引用。一般 API 無 delete／update 舊紀錄入口。資料庫管理員仍有管理權限，這不是防 DBA 篡改的密碼學存證。

`test_quality_revisions.py` 驗證跨租戶讀取／批准／評分、manager／reviewer／worker 越權、40 分不能繞 QA、舊批准不授權新稿、重複／衝突提交、並行版本錯置、DB 原始 SQL 改刪／RLS 插入拒絕及發布文字防改。既有並行預算、撤銷／過期、Kill Switch、未知結果不盲重試測試保留。

Log 只記事件識別，不記原始文案或品牌資料；測試檢查私密合成品牌值與憑證不出現在 log／audit。SQLAlchemy hide_parameters 保持 true。所有 write 仍受既有共享速率限制。Prompt 只載入固定 allowlist 產業路徑，輸入是資料，不能更動租戶、工具、QA、Budget 或 Approval。

界限：lexical QA 無法辨識所有變體、隱含醫療／金融／法律宣稱或社會偏見；美國官方來源僅作合成案例參考，未完成營運地合規審查。未知產業、缺乏專業證據或語義不明必須人工查核。資料庫未新增靜態加密或正式 DLP；真實品牌資料仍禁止進入本階段。
