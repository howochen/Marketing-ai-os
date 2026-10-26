# MOS-CONTENT-001：實作及安全審查

來源：7504ae14888b6b55f82406614c9e656bea3f98ec。獨立分支：codex/marketing-ai-os-content-workbench。

## 技術盤點與重用

| 既有元件 | 本次使用方式 |
|---|---|
| main.Task／Tenant／task_for／lock_tenant | 同一任務儲存及租戶鎖；不重建任務系統 |
| A09／Agent Runtime | 保留原介面；人工流程不呼叫生成器、不產生虛構Agent Run或Provider收據 |
| A21 agent_runtime.qa／quality.rule_scores | 沿用硬性規則及明確標示來源的品質資料，另提供逐項繁中原因 |
| DraftRevision／revisions.revise | 不可覆寫、idempotency、父版本檢查、舊版還原另存 |
| approve_revision／RevisionApproval | 精確最新版核准；新增撤銷目前指標，保留舊批准及Audit |
| Audit／require／scope／FORCE RLS | 同一認證、CSRF、RBAC、租戶隔離，不另建登入 |
| /app shell／app.css／social_ui | 加入內容導覽與content.js，無第二套前端框架 |
| publication-request | 抽出共用queue_publication，原路由不變；發布計畫在同交易排入MANUAL_REQUIRED，絕不呼叫執行器 |

## 狀態對應

| 工作台詞彙 | 真實資料狀態 |
|---|---|
| DRAFT | Task.status=DRAFT，尚無Revision |
| EDITED | 新增HUMAN Revision，不新增Task狀態 |
| QA REVIEW | Task.status=PENDING_APPROVAL；獨立QA結果可通過或失敗 |
| OWNER APPROVED | Task.status=APPROVED，approved_revision_id精確等於latest_revision_id |
| READY FOR PUBLICATION | 上述核准有效的內容顯示詞，非新狀態；Publication仍MANUAL_REQUIRED |
| PLAN_SAVED／REAPPROVAL_REQUIRED | 計畫視圖根據目前核准指標計算，不改寫Task狀態或Worker派送狀態 |

舊Revision上的批准紀錄是歷史事實，不等於目前授權。重新核准曾撤銷版本會再次寫Audit；新Revision永不繼承指標。計畫永遠保留原Revision，不自動換文。發布前既有驗證仍會拒絕失效核准。

## API

新增 `/ui/content` 下：

- `GET/POST /tasks`：租戶任務列表／人工需求建立，POST具固定idempotency key。
- `GET/PUT /tasks/{task_id}`：讀取／首版文案前修改需求，PUT須expected_version。
- `POST /tasks/{task_id}/manual-draft`：建立第一個HUMAN Revision，硬QA失敗仍保存但不得批准。
- `POST /tasks/{task_id}/snapshot`：舊輸出轉既有原始Revision快照；重複呼叫不重複建立。
- `GET /tasks/{task_id}/compare?before=...&after=...`：全文／Hook／CTA任意兩版diff。
- `GET /tasks/{task_id}/revisions/{rid}/checks`：A21結果、逐項原因及UNEVALUATED項目。
- `POST /tasks/{task_id}/revisions/{rid}/revoke`：僅Owner撤銷目前核准，append-only Audit。
- `POST /tasks/{task_id}/plans`、`GET /plans`：精確核准版計畫、未來時間與時區檢查；要求Owner及publish scope。

編輯與核准直接使用原有 `/tasks/{id}/revisions`、`.../{rid}/approve`；原有rerun QA、品質評分與Publication API繼續相容。列表最多200筆並明示上限，未增加搜尋平台或大型工作流。

## Migration0012

只新增nullable `tasks.content_brief` JSON與 `content_plans`。舊列保持NULL，不推斷品牌事實、不重算帳目。新表綁tenant／task／revision複合外鍵，具idempotency唯一鍵、PostgreSQL FORCE RLS及SQLite／PostgreSQL不可UPDATE／DELETE trigger，ORM亦拒絕改寫。計畫修正採另存新計畫，保留歷史。

ready與現有安裝器的schema檢查同步0012；這僅是程式修改，沒有執行原環境安裝器、遷移原DB或修改Vault。遷移前須備份；downgrade拒絕破壞歷史，回復使用已核對的備份。隔離測試包括0011資料升級及全新PostgreSQL遷移。

## 安全與限制

瀏覽器沿用HttpOnly Cookie及CSRF；所有內容輸出HTML escape，diff用純文字，不引入外部JS／分析。Audit只記ID及動作，不記全文或品牌資料。伺服器租戶鎖及Revision parent保護並行編輯；舊版批准與跨租戶ID均不能授權新內容。

QA只做已定義的格式／字串／長度規則；品牌語氣、共鳴、成效、事實與法規適用皆UNEVALUATED。Owner確認是人工審核，不能視作法規認證。尚未儲存的文字只在記憶體，崩潰可能遺失；不為此新增敏感資料本機快取。

本機啟動器只聽127.0.0.1:8893；使用獨立SQLite及既有一次性登入，不讀寫DPAPI。它不適合公開或正式多使用者部署。未變更Threads OAuth、Meta設定、ngrok、加密Token或手機初始化實際開關。

## 套件與成本

沒有新框架、SDK或付費服務。`tzdata==2026.5`原已在constraints／開發環境鎖定，本次明列為runtime直接依賴，確保Windows `zoneinfo` 無系統IANA資料時可用；約348KB wheel，Apache-2.0，由Python維護者持續發佈。替代方案是依賴Linux系統tzdata，但不能保障Windows啟動器；自行維護UTC offset會錯過DST，因此不採用。

查核2026-10-26：[Python zoneinfo官方文件](https://docs.python.org/3/library/zoneinfo.html)、[tzdata版本及授權](https://pypi.org/project/tzdata/2026.5/)。漏洞掃描結果保存在content/audit.txt。本次人工工作流真實AI呼叫0、模擬生成呼叫0、真實API成本USD0；人工輸入不冒充Mock Token或模型帳單。只增加本機執行期間的一個Uvicorn程序、SQLite檔案；測試Docker專案使用獨立資源，無新常駐服務。
