# P0 已知限制 — MOS-P0-009

本工單離線收尾 PASS，**不代表商用就緒**。本次未開始 P1。

1. 認證為管理員人工核身／交付單次 challenge；無 email delivery、OAuth IdP、登入 abuse/rate limiting。owner／worker 是可到期、可撤銷 bearer 身分，非硬體 attestation。
2. 只有可信 worker 可結算，但假收據無法由本機檢查完全辨識；外部 importer 必須對供應商帳戶驗真。實際付費 API 未執行。
3. 目前只有單次輸入 token cap、輸出上限與 tenant 美元預算；DRAFT 可建立，超預算拒絕 funded execution。沒有每月 token quota／帳期自動重設。
4. 四社群平台皆 manual_only；無真實授權／發布／回調。沒有 webhook 端點；404 fail-closed 測試不代表 webhook 簽章、防重播、事件去重已完成。
5. 超時 task 回收需 operator／scheduler 呼叫端點。已送出的模型請求不能靠 kill switch 取消；未知結果保持保留款，不盲目重試。
6. SQLite 僅供本機；raw SQL tenant isolation 依賴 PostgreSQL RLS。受信任 API server 能設定 tenant context，DB owner／admin 也能改安全設定，無法宣稱抵抗這些身分被入侵。
7. 尚無 production HTTPS、反向代理 log redaction 驗證、secret manager、加密備份還原演練、監控／告警、實際負載與災難復原證據。
8. 價格卡還沒有歷史版本表、發票／折扣／region／1h cache 對帳。部署前需再次核對供應商來源及 model lifecycle；本次未將既有卡當成即時報價。
9. 老版 float schema baseline 會拒絕，不自動轉換、不 promote 舊 API key、不 downgrade；只有備份／平行轉換／回滾規劃，見 P0_DATABASE_MIGRATION_PLAN.md。
10. REMOTE_CI_NOT_VERIFIED：已檢查 YAML 結構與本機相同命令，但沒有聲稱遠端 runner 已通過。現有型別檢查 NOT_CONFIGURED；靜態檢查為 AST／compileall／JSON／YAML／Compose，不是完整 lint、SAST 或滲透測試。
11. 一項 TestClient HTTPX deprecation warning。依賴仍為 bounded ranges，掃描是本次 resolver snapshot 的零已知漏洞，不是永久保證／部署 lockfile。
12. API key 不出現在本次受測 logger／stdout／stderr／audit／錯誤回應；外部代理、自訂 handlers、使用者將秘密放入任務內容等路徑未由此測試保證。

P1 必須另行授權；先補足必要基礎設施，並維持禁止自動真實發布的邊界。
