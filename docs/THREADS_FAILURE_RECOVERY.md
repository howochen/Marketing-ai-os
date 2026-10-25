# Threads故障與人工處理

| 狀態／情境 | 處理 |
|---|---|
| 未設定App／key／HTTPS callback | BLOCKED_BY_PLATFORM_SETUP；不呼叫官方API |
| OAuth state錯誤／Cookie不符／過期／重放／owner失效 | 拒絕；交換失敗的已用state不可重送code，重新OAuth |
| AUTH_REQUIRED／TOKEN_EXPIRED／PERMISSION_DENIED | 停止並重新授權／核對scope；本地撤銷立即停用，Provider撤銷另由帳號設定完成 |
| quota不足／未知quota | 不建立Container；已知純preflight失敗可由owner顯式retry-preflight，沒有自動輪詢重試 |
| CONTAINER_CREATED／IN_PROGRESS | 保留原container；worker顯式繼續時只在官方FINISHED後發布同一container，不建第二個 |
| Container ERROR／EXPIRED | MANUAL_REQUIRED；不換ID、不自動新建或繞過原Revision綁定 |
| CREATING_CONTAINER／PUBLISHING逾時、5xx、無效JSON或ID、程序崩潰 | RESULT_UNKNOWN；保存dispatch marker及已知ID，不盲目POST |
| Worker重啟 | 現有/maintenance/recover在60秒後只標記未知，不發HTTP；再次Recovery冪等 |
| 發布回應有Media ID、GET暫不可讀／文字或owner不符 | PUBLISHED_UNVERIFIED；保存ID，reconcile只重做GET |
| 容器已PUBLISHED卻沒有Media ID | RECONCILIATION_REQUIRED；不把container當media、不推測近似貼文，不POST |
| 已知Media ID | execute回既有紀錄，不再發布；核對用reconcile |
| 另一篇同帳號有未解決dispatch | 拒絕新發送，先人工查明原結果 |
| Kill Switch／帳號停用／owner或worker撤銷 | 拒絕尚未發送操作；不能撤回已進入供應商處理中的請求 |

未知結果無法靠本地交易證明外部exactly-once。人工可到本人Threads／Meta後台檢查實際貼文，再保留官方讀回證據；本版沒有「隨便填ID即標成功」或清除未知marker重發API。無法查明時維持凍結。不要直接SQL改status／delete歷史或重新使用同一Revision開另一工作。

Token密文與外部Fernet key分開備份。資料庫還原需保留OAuth used狀態、Publication markers及idempotency，並在啟動前停用HTTP／publishing；遺失key必須重新授權。非破壞性回滾採獨立DB驗證備份後的切換規劃，不執行有資料刪除的downgrade。本次18表合成還原結果見threads/backup-restore.json；不代表Production RTO/RPO保證。
