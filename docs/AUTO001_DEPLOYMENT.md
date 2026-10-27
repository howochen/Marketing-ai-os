# MOS-AUTO-001 部署與真人驗收界線

**尚未部署。以下操作需要另外批准，本次沒有執行。** 新 migration 0014 僅在隔離測試；原 DB、OAuth、DPAPI、ngrok 與正式帳號配置保留。

## 程式與資料差異

- 新增 AutomationPolicy／AutomationSlot 兩表，Tenant FORCE RLS、唯一排程鍵、政策條款與身份不可覆寫；不重建 Task、Revision、Publication 或 Ledger。
- Publication 增加精確政策 ID；DB trigger 保留原人工核准，另允許有精確 slot／Revision／QA 的 FULL 政策分支。首次綁定必須 ACTIVE，既有在途結果仍可保存。手動發布端點不能挪用自動化授權。
- ThreadsConnection 新增 nullable authorized_at；只有新的官方 OAuth 成功時寫入，不用刷新時間回填舊帳號。刷新繼續使用 token_issued_at 判斷 24h，回呼用 authorized_at 判斷舊事件。未知舊授權時間轉待審，不能假裝已確認。
- policy Worker 是 automation_worker，只有 automation 與單一 policy scope，效期等於政策到期；一般 execute／settle／recover／admin 路由不接受它。授權者登入到期不使政策失效；撤銷授權者憑證仍會停機，包括原系統「登出即撤銷」行為。登出後若要恢復，需重新核對政策版本；沒有新增永久管理員身分。
- 每次生成先持久化名額、Task 與 Ledger 預留；當機／未知結果不自動重生。每日時段過三分鐘不補發，未知結果阻擋後續自動化。沒有外部 exactly-once 保證。

## 待批准的部署順序

1. 固定待部署 SHA、檢查最新 CI、保存原映像／Vault，安排維護窗與新一致性備份，依既有備份流程驗證可復原。不覆蓋唯一原 volume；失敗時從備份還原新庫，再切回舊映像，避免丟失新收據／撤銷證據。
2. **另行批准**原 DB 的 0013／0014 升級與 API 更新。0013 官方 Privacy Callback 相容性仍有前階段 NOT_VERIFIED，不能因本次自動化回歸通過就公開這些端點；部署前必須明確處理路由暴露範圍，否則 NO-GO。本次沒有重新開發或驗證 Privacy Callback 規格。
3. 確認本人帳號的官方來源、scope、expiry、App 綁定與 authorized_at。舊資料不可推測授權時間；必要時本人重新 OAuth 一次，不重輸 App Secret。不得宣稱本次已唯讀檢查真實帳號。
4. 官方模型費率、完整 request 上界、帳戶可用性與 Provider Key 的安全配置通過後，取得另外的實際支出授權；維持每次及整批上限。既有程式 Release Gate 本版仍鎖定，須另行審查解除，不能只改環境變數。
5. 經批准先做一次真實 AI 生成但不發布，保存 Provider usage／Response ID、既有 Ledger 結算與 QA。確認 bytes、估計 tokens、Provider usage、模擬成本及待驗真成本不混用；沒有 Invoice 不得標驗真。
6. Owner 核對一篇確切測試文字、Revision、目標 Threads 帳號與發布時間，**另行批准只發這一篇**。不要啟用持續 FULL 政策代替單篇真實測試。用既有兩階段 Publisher 取得 Published Media ID，讀回 ID／文字／帳號／官方 permalink；未知結果停止，不盲目重發。
7. 一篇成功不延伸成持續授權。再取得有期限、每日篇數、時段、素材與每月預算上限的持續政策批准後，才審查並開啟對應 Live flags／Worker。

## 背景 Worker 與 Windows

現有 runtime Docker image 內含 `python -m app.automation_worker`；新增 Compose `automation` profile、restart unless-stopped、無公開 port。每個受控 Tenant 一個最小 Worker，從既有 DB 與加密金鑰取得 Owner 啟用政策時已產生的狹義憑證。沒有常駐多 Agent、Kafka 或 Celery。

服務預設 `MOS_AUTOMATION_ENABLED=false`；模型、HTTP、發文及手機通道仍為 false。部署人員需一次配置 Tenant ID、既有受控 DB／Vault 與該 profile；一般使用者只操作政策。不要把密鑰或 Worker Token 貼入 shell history、Git 或前端。

Windows 必須先有 Docker 引擎；Docker Desktop 若設定登入後啟動，restart policy 可恢復既有 Worker，不需要每天開瀏覽器。本次沒有修改 Windows 啟動設定，也沒有驗證「無人登入即可啟動 Docker」或真的重開機；需要這種運作方式時要另確認主機／登入條件，不宣稱已完成 Windows Service 安裝。

首次啟用需要由部署人員在已批准的環境執行該 profile，不是本次可以直接執行的指令：`docker compose --profile automation up -d automation`。執行前必須完成上述 migration、暴露範圍與成本授權。不得對現在的原專案嘗試。

## 最小剩餘批准事項

1. 維護窗內的原資料庫升級、API／單一 Tenant Worker 部署與明確路由暴露範圍。
2. 一次受控 Provider 測試的具體 USD 上限、模型及請求次數，以及安全 Key 配置。
3. 一篇精確文案／Revision／Threads 帳號的真實測試發布。
4. 第 3 項成功後，獨立批准有上限及期限的持續自動化政策。

上述批准互不自動延伸。正式營運與無限制自主創作均不在本次驗收範圍。
