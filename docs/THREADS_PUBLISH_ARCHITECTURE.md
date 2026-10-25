# A13 Threads Publisher架構

A13為確定性後端角色，新增threads_api／threads_routes／threads_publisher，保留A01/A09/A21/A23、Ledger、Revision及Approval。沒有LLM判斷、工具呼叫或新常駐Agent；其他平台ADAPTERS維持ManualAdapter。原Threads通用publication-request也維持MANUAL_REQUIRED；只有新的明確owner確認流程可開始A13。

Migration0009新增threads_connections／threads_oauth_states（RLS），在既有Publication增加帳號、hash、container/media ID、trace、進度、次數、錯誤與讀回時間等欄位。approved_revision_id直接重用既有revision_id，不另造內容／批准表。舊status是相容的manual queue標示；publish_status才是A13外部執行進度，API依此顯示，不能將舊status解讀成已發文。舊row與審核紀錄不覆寫；destructive downgrade拒絕。

1. 現有A09或人工Revision產生文字，通過A21，owner核准指定Revision。
2. POST /tasks/{id}/publication-request建立原有不可變content_snapshot與revision_id。
3. owner以POST /threads/publications/{id}/authorize提交connection_id、官方threads_user_id、revision_id、文字UTF8 SHA256、confirm_public_post=true。這是逐篇公開確認；不接受1、字串true或客戶端自稱已批准。
4. 帳號owner另以POST /threads/connections/{id}/publishing啟用指定Tenant／Account，需即時me/debug核對。全域MOS_THREADS_PUBLISH_ENABLED也是必要條件；Tenant disabled／budget_paused作為停止條件重用，沒有新AI成本帳本。
5. worker POST /threads/publications/{id}/execute：重查owner批准有效、最新Revision、相同文字／hash、A21、owner逐篇確認、Tenant／Account／來源／Token／scope、即時quota。拒絕其他未解決帳號dispatch。
6. APPROVED→READY_TO_PUBLISH→CREATING_CONTAINER（先commit）→官方建立→CONTAINER_CREATED（保存ID並commit）→GET容器狀態→PUBLISHING（先commit）→官方發布→PUBLISHED_UNVERIFIED（另存Media ID並commit）→GET讀回。只有OFFICIAL_API來源且id／owner／username／text／TEXT_POST／合法HTTPS permalink／timestamp全符合才PUBLISHED_VERIFIED。

每次POST前先持久化marker再重新鎖Tenant查開關／權限；HTTP期間持鎖，兩個Worker不能同時發送。租戶鎖不是外部exactly-once保證。DB保護Revision內容、帳號／hash／逐篇核准者、既有container/media ID、計數不倒退與合法狀態遷移；unique(tenant,account,revision)防同版本另建發文工作。

任何in-flight POST失敗保守RESULT_UNKNOWN，即使回應429亦不自動重送；錯誤類別保留於last_error_category。重啟Recovery將過期CREATING_CONTAINER/PUBLISHING轉RESULT_UNKNOWN，不發任何HTTP。reconcile只GET與人工處理，不能POST重發。不知道Published ID時，不以近似文字或第一篇搜尋結果推測ID。

**排程尚未開發／啟用**：依工單須先真實立即發文成功。本次沒有那項前提，因此不提前加scheduler或自動發文。現有Recovery只做保守回收。
