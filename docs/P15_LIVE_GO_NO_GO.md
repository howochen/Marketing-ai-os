# P1.5 Live GO／NO-GO（P1.3 後）

審核日2026-10-26；此文件不是支出授權。

| 判斷項目 | 結論 | 證據與尚缺條件 |
|---|---|---|
| 1. 受控、小額真實模型測試 | **NO-GO** | Durable gate／batch caps／Recovery已完成離線驗證，但Live transport仍硬性禁用；需獨立工單、人類支出授權、實際成本上界及供應商接入審查 |
| 2. 真實供應商費率與帳戶可用性證據 | **未具備** | P12有2026-10-25公開文件／reference rate snapshots；沒有重新查本帳戶models/tier/額度／稅費／實際cache與額外費用，不能把公開文件當帳戶可用性證據 |
| 3. 另外取得的實際支出授權 | **沒有** | 只有SYNTHETIC_TEST_AUTHORIZATION，不能轉成可扣款授權；需實際操作人、環境、模型、每次／整批USD與次數、有效期間、停止條件的獨立核准 |
| 4. 真實Provider usage處理 | **格式準備已測，實際流程未驗證** | OpenAI usage parser／cache與reasoning分類通過Mock合約，尚無真實usage來源驗證、帳戶對帳／invoice importer；P13介面只接MOCK，禁止INVOICE_VERIFIED |
| 5. 正式營運 | **NO-GO** | 沒有Production啟動、客戶資料／社群帳號操作、正式環境安全／備援／法律合規或真實品質驗收；即使將來第1項GO也不能推論本項GO |

P1.3完成的是持久化名額／資金預留、程序重啟、並行與未知結果處理；P12所列durable gate缺口已有離線證據，不再把它列成「完全沒做」。剩餘缺口是實際供應商、有效支出授權、Live安全整合、真實usage/invoice驗證與營運條件。

未來若獲明確小額授權，還必須重新核對模型ID／account tier／完整輸入與最大輸出／cache write／reasoning／區域及額外功能費用；所有未知項目拒絕發送，維持tools/fallback/retry禁令與MANUAL_REQUIRED。不能只把MOS_MODEL_CALLS_ENABLED或MOS_LIVE_TESTS改true、提供key就繞過現有real-transport禁令。

外部API無法和本地DB形成原子exactly-once交易。已送出、費率變更或延遲帳單可能超過本地預留；需資金緩衝／停止規則／受信任對帳，而不是承諾外部帳單絕對不超支。
